import base64
import binascii
import json
from datetime import datetime

from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    jsonify,
    redirect,
    render_template,
    request,
    stream_with_context,
    url_for,
)

from ai import STATUSES, AIUnavailableError
from extensions import db
from integrations import (
    IntegrationDisabled,
    IntegrationUnavailable,
    coerce_tool_args,
)
from images import downscale_image, to_base64, upload_limit_message
from models import Assessment, Plant

# User-facing pages and the assessment API live under a descriptive prefix.
URL_PREFIX = "/plant-health-records"

bp = Blueprint("health", __name__, url_prefix=URL_PREFIX)
# Infrastructure probes stay at the root, where orchestrators expect them.
root_bp = Blueprint("root", __name__)

MAX_DESCRIPTION_CHARS = 4000
MAX_PLANT_REF_CHARS = 200
RECENT_LIMIT = 10


def _client():
    return current_app.extensions["ollama"]


@root_bp.route("/")
def root_redirect():
    return redirect(url_for("health.index"))


@root_bp.route("/healthz")
def healthz():
    client = _client()
    ai_up = client.ping()
    body = {
        "service": "health-monitoring-service",
        "status": "ok" if ai_up else "degraded",
        "ai": {
            "url": client.base_url,
            "model": client.model,
            "reachable": ai_up,
            # Startup preload progress: not_started / pending / loading / retrying /
            # loaded / failed. "loaded" means the first assessment will be warm.
            "preload": getattr(client, "preload_state", None),
        },
    }
    return jsonify(body), 200 if ai_up else 503


@bp.route("/")
def index():
    return render_template("index.html", recent=_recent(), plants=Plant.ordered())


@bp.route("/<int:assessment_id>")
def view_assessment(assessment_id):
    assessment = db.session.get(Assessment, assessment_id)
    if assessment is None:
        abort(404)
    return render_template(
        "detail.html",
        assessment=assessment,
        recent=_recent(exclude_id=assessment_id),
        plants=Plant.ordered(),
    )


@bp.route("/<int:assessment_id>/image")
def assessment_image(assessment_id):
    assessment = db.session.get(Assessment, assessment_id)
    if assessment is None or not assessment.image_data:
        abort(404)
    return Response(
        assessment.image_data,
        mimetype=assessment.image_mime or "image/jpeg",
        headers={"Cache-Control": "private, max-age=86400"},
    )


def _recent(limit: int = RECENT_LIMIT, exclude_id: int | None = None):
    query = Assessment.query
    if exclude_id is not None:
        query = query.filter(Assessment.id != exclude_id)
    return (
        query.order_by(Assessment.created_at.desc(), Assessment.id.desc())
        .limit(limit)
        .all()
    )


@bp.route("/assessments", methods=["POST"])
def create_assessment():
    wants_html = _wants_html()

    try:
        plant_ref, description, image_b64, image_mime = _read_input()
    except ValueError as exc:
        return _error(str(exc), 400, wants_html)

    client = _client()
    try:
        result = client.assess(
            description=description, image_b64=image_b64, plant_ref=plant_ref
        )
    except AIUnavailableError as exc:
        return _error(str(exc), 503, wants_html)

    assessment = _persist(result, client, plant_ref, description, image_b64, image_mime)

    if wants_html:
        return render_template("_assessment.html", assessment=assessment)
    return jsonify(assessment.to_dict()), 201


@bp.route("/assessments/stream", methods=["POST"])
def stream_assessment():
    """Server-sent events reporting progress while the model works."""

    try:
        plant_ref, description, image_b64, image_mime = _read_input()
    except ValueError as exc:
        return _sse_error(str(exc))

    return _stream(plant_ref, description, image_b64, image_mime)


def _stream(plant_ref, description, image_b64, image_mime) -> Response:
    client = _client()
    app = current_app._get_current_object()

    def generate():
        try:
            for event in client.assess_stream(
                description=description, image_b64=image_b64, plant_ref=plant_ref
            ):
                if event["type"] == "result":
                    assessment = _persist(
                        event["result"], client, plant_ref, description, image_b64, image_mime
                    )
                    html = render_template("_assessment.html", assessment=assessment)
                    yield _sse(
                        {"type": "done", "id": assessment.id, "html": html}
                    )
                    return
                if event["type"] == "error":
                    yield _sse({"type": "error", "message": event["message"]})
                    return
                yield _sse(event)
        except Exception:  # noqa: BLE001 - the stream must always terminate cleanly
            app.logger.exception("streaming assessment failed")
            yield _sse(
                {"type": "error", "message": "The assessment failed unexpectedly."}
            )

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def _sse_error(message: str) -> Response:
    return Response(
        _sse({"type": "error", "message": message}),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


def _persist(result, client, plant_ref, description, image_b64, image_mime) -> Assessment:
    assessment = Assessment.from_result(
        result,
        model=client.model,
        plant_ref=plant_ref,
        description=description,
        has_image=image_b64 is not None,
        image_mime=image_mime,
        image_data=base64.b64decode(image_b64) if image_b64 else None,
    )
    db.session.add(assessment)
    # A name used for the first time becomes a title offered on the form.
    Plant.register(plant_ref)
    db.session.commit()
    return assessment


@bp.route("/assessments", methods=["GET"])
def list_assessments():
    """List assessments, newest first.

    Filters: ``plant_ref`` (exact), ``status``, ``since`` (ISO-8601, records created
    at or after it). Paging: ``limit`` (1-200) and ``offset``. The shared MCP and RAG
    servers page through this endpoint; it never returns image bytes.
    """

    query = Assessment.query
    plant_ref = request.args.get("plant_ref")
    if plant_ref:
        query = query.filter_by(plant_ref=plant_ref)

    status = request.args.get("status")
    if status:
        if status not in STATUSES:
            return jsonify({"error": f"status must be one of: {', '.join(STATUSES)}"}), 400
        query = query.filter_by(status=status)

    since = request.args.get("since")
    if since:
        try:
            since_at = datetime.fromisoformat(since.replace("Z", "+00:00"))
        except ValueError:
            return jsonify({"error": "since must be an ISO-8601 timestamp"}), 400
        # created_at is stored naive (UTC); compare like with like.
        query = query.filter(Assessment.created_at >= since_at.replace(tzinfo=None))

    limit = request.args.get("limit", default=50, type=int)
    limit = max(1, min(limit, 200))
    offset = max(0, request.args.get("offset", default=0, type=int))

    assessments = (
        query.order_by(Assessment.created_at.desc(), Assessment.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return jsonify([a.to_dict() for a in assessments])


@bp.route("/assessments/<int:assessment_id>", methods=["GET"])
def get_assessment(assessment_id):
    assessment = db.session.get(Assessment, assessment_id)
    if assessment is None:
        return jsonify({"error": "assessment not found"}), 404
    return jsonify(assessment.to_dict())


@bp.route("/assessments/<int:assessment_id>", methods=["PATCH", "PUT"])
def update_assessment(assessment_id):
    """Edit the plant name/reference and description recorded against a report.

    The AI verdict itself is never rewritten — it is the output of a past model
    run and editing it would misrepresent what the model actually said. Only the
    caller-supplied context is editable; use ``/regenerate`` to get a fresh
    verdict from the corrected context.
    """

    wants_html = _wants_html()
    assessment = db.session.get(Assessment, assessment_id)
    if assessment is None:
        return _error("assessment not found", 404, wants_html)

    try:
        changes = _read_edit_input(replace=request.method == "PUT")
    except ValueError as exc:
        return _error(str(exc), 400, wants_html)

    for field, value in changes.items():
        setattr(assessment, field, value)
    Plant.register(changes.get("plant_ref"))
    db.session.commit()

    if wants_html:
        return render_template("_submission.html", assessment=assessment, plants=Plant.ordered())
    return jsonify(assessment.to_dict())


@bp.route("/assessments/<int:assessment_id>", methods=["DELETE"])
def delete_assessment(assessment_id):
    assessment = db.session.get(Assessment, assessment_id)
    if assessment is None:
        return jsonify({"error": "assessment not found"}), 404

    db.session.delete(assessment)
    db.session.commit()

    if request.headers.get("HX-Request") == "true":
        # htmx never swaps a 204, so an empty 200 is what removes the row.
        return ""
    return "", 204


@bp.route("/assessments/<int:assessment_id>/regenerate", methods=["POST"])
def regenerate_assessment(assessment_id):
    """Re-run the model over an existing record's photo and description.

    The original report is kept: a second opinion is a new record, so the two
    runs can be compared rather than one silently replacing the other.
    """

    wants_html = _wants_html()
    assessment = db.session.get(Assessment, assessment_id)
    if assessment is None:
        return _error("assessment not found", 404, wants_html)

    try:
        plant_ref, description, image_b64, image_mime = _source_input(assessment)
    except ValueError as exc:
        return _error(str(exc), 400, wants_html)

    client = _client()
    try:
        result = client.assess(
            description=description, image_b64=image_b64, plant_ref=plant_ref
        )
    except AIUnavailableError as exc:
        return _error(str(exc), 503, wants_html)

    repeat = _persist(result, client, plant_ref, description, image_b64, image_mime)

    if wants_html:
        return render_template("_assessment.html", assessment=repeat)
    return jsonify(repeat.to_dict()), 201


@bp.route("/assessments/<int:assessment_id>/regenerate/stream", methods=["POST"])
def stream_regenerate_assessment(assessment_id):
    assessment = db.session.get(Assessment, assessment_id)
    if assessment is None:
        return _sse_error("assessment not found")

    try:
        plant_ref, description, image_b64, image_mime = _source_input(assessment)
    except ValueError as exc:
        return _sse_error(str(exc))

    return _stream(plant_ref, description, image_b64, image_mime)


def _source_input(assessment: Assessment):
    """The inputs to feed the model when reassessing an existing record."""

    image_b64 = to_base64(assessment.image_data) if assessment.image_data else None
    if not assessment.description and not image_b64:
        raise ValueError(
            "This record has neither a description nor a stored photo, so it cannot "
            "be assessed again. Submit a new assessment instead."
        )
    return assessment.plant_ref, assessment.description, image_b64, assessment.image_mime


def _read_edit_input(*, replace: bool) -> dict:
    """Return the editable fields supplied by the caller.

    With ``replace`` (PUT) every editable field is set, so an omitted field is
    cleared. Otherwise (PATCH, and the UI's edit form) only supplied fields move.
    """

    source = request.get_json(silent=True) or {} if request.is_json else request.form
    limits = {"plant_ref": MAX_PLANT_REF_CHARS, "description": MAX_DESCRIPTION_CHARS}

    changes = {}
    for field, limit in limits.items():
        if field in source:
            changes[field] = _clean(source.get(field), limit, field)
        elif replace:
            changes[field] = None

    if not changes:
        raise ValueError(
            f"Provide at least one field to update: {', '.join(sorted(limits))}."
        )
    return changes


def _wants_html() -> bool:
    """Whether to answer with an HTML fragment rather than JSON.

    HTMX always gets HTML. Otherwise fall back to content negotiation, so a plain
    API client posting multipart/form-data still receives JSON.
    """

    if request.headers.get("HX-Request") == "true":
        return True

    accept = request.accept_mimetypes
    if not accept.provided:
        return False
    # A tie (e.g. "*/*" or no preference) falls through to JSON, the API default.
    return accept["text/html"] > accept["application/json"]


def _error(message: str, code: int, wants_html: bool):
    if wants_html:
        return render_template("_error.html", message=message), code
    return jsonify({"error": message}), code


def _read_input() -> tuple[str | None, str | None, str | None, str | None]:
    """Return (plant_ref, description, image_b64, image_mime) from form or JSON input."""

    if request.is_json:
        data = request.get_json(silent=True) or {}
        plant_ref = _clean(data.get("plant_ref"), MAX_PLANT_REF_CHARS, "plant_ref")
        description = _clean(data.get("description"), MAX_DESCRIPTION_CHARS, "description")
        image_b64, image_mime = _read_json_image(data)
    else:
        plant_ref = _clean(request.form.get("plant_ref"), MAX_PLANT_REF_CHARS, "plant_ref")
        description = _clean(
            request.form.get("description"), MAX_DESCRIPTION_CHARS, "description"
        )
        image_b64, image_mime = _read_uploaded_image()

    if not description and not image_b64:
        raise ValueError("Provide an image, a text description, or both.")

    return plant_ref, description, image_b64, image_mime


def _read_json_image(data: dict) -> tuple[str | None, str | None]:
    raw = data.get("image_base64")
    if raw is None:
        return None, None
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("image_base64 must be a non-empty base64 string")

    raw = raw.strip()
    mime = None
    if raw.startswith("data:"):
        header, _, encoded = raw.partition(",")
        if not encoded:
            raise ValueError("image_base64 data URL is malformed")
        mime = header[5:].split(";")[0] or None
        raw = encoded

    try:
        decoded = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("image_base64 is not valid base64") from exc

    if not decoded:
        raise ValueError("image_base64 decoded to an empty image")
    if len(decoded) > current_app.config["MAX_CONTENT_LENGTH"]:
        raise ValueError(upload_limit_message(current_app.config["MAX_CONTENT_LENGTH"]))

    allowed = current_app.config["ALLOWED_IMAGE_TYPES"]
    if mime is not None and mime not in allowed:
        raise ValueError(f"Unsupported image type '{mime}'. Allowed: {', '.join(sorted(allowed))}")

    decoded, new_mime = downscale_image(decoded, current_app.config["IMAGE_MAX_EDGE"])
    return to_base64(decoded), new_mime or mime


def _read_uploaded_image() -> tuple[str | None, str | None]:
    file = request.files.get("image")
    if file is None or not file.filename:
        return None, None

    mime = (file.mimetype or "").lower()
    allowed = current_app.config["ALLOWED_IMAGE_TYPES"]
    if mime not in allowed:
        raise ValueError(
            f"Unsupported image type '{mime or 'unknown'}'. Allowed: {', '.join(sorted(allowed))}"
        )

    payload = file.read()
    if not payload:
        raise ValueError("The uploaded image is empty")

    payload, new_mime = downscale_image(payload, current_app.config["IMAGE_MAX_EDGE"])
    return to_base64(payload), new_mime or mime


def _clean(value, max_chars: int, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    value = value.strip()
    if not value:
        return None
    if len(value) > max_chars:
        raise ValueError(f"{field} must be {max_chars} characters or fewer")
    return value


# --------------------------------------------------------------------------- #
# Plant names: the titles offered on the form, managed on their own page        #
# --------------------------------------------------------------------------- #


@bp.route("/plants", methods=["GET"])
def list_plants():
    """The plant names on offer. A browser gets the management page, API clients JSON."""

    plants = Plant.ordered()
    if _wants_html():
        return render_template("plants.html", plants=plants)
    return jsonify([p.to_dict() for p in plants])


@bp.route("/plants", methods=["POST"])
def create_plant():
    """Add a plant name (JSON or form ``name``). Re-adding an existing name is a no-op."""

    wants_html = _wants_html()
    source = request.get_json(silent=True) or {} if request.is_json else request.form
    try:
        name = _clean(source.get("name"), MAX_PLANT_REF_CHARS, "name")
        if not name:
            raise ValueError("Provide a plant name.")
    except ValueError as exc:
        return _error(str(exc), 400, wants_html)

    existed = Plant.find(name) is not None
    plant = Plant.register(name)
    db.session.commit()

    if wants_html:
        return render_template("_plant_list.html", plants=Plant.ordered())
    return jsonify(plant.to_dict()), 200 if existed else 201


@bp.route("/plants/<int:plant_id>", methods=["DELETE"])
def delete_plant(plant_id):
    """Remove a name from the list. Assessments recorded under it are untouched."""

    plant = db.session.get(Plant, plant_id)
    if plant is None:
        return jsonify({"error": "plant not found"}), 404

    db.session.delete(plant)
    db.session.commit()

    if request.headers.get("HX-Request") == "true":
        return ""  # htmx never swaps a 204; an empty 200 removes the row
    return "", 204


# --------------------------------------------------------------------------- #
# Release 1: shared local MCP + RAG servers, reached only through this backend  #
# --------------------------------------------------------------------------- #

MAX_QUESTION_CHARS = 500


def _mcp():
    return current_app.extensions["mcp"]


def _rag():
    return current_app.extensions["rag"]


def _integration_error(exc: Exception, wants_html: bool, *, fragment: str = "_error.html"):
    """Map integration failures to honest status codes: 400 input, 503 disabled,
    502 shared server unreachable / failed."""

    if isinstance(exc, ValueError):
        code = 400
    elif isinstance(exc, IntegrationDisabled):
        code = 503
    else:
        code = 502
    if wants_html:
        return render_template(fragment, message=str(exc), error=True, code=code), code
    return jsonify({"error": str(exc), "status_code": code}), code


@bp.route("/integrations")
def integrations_status():
    """Wiring status of both integrations. Probes only when a mode is enabled, so
    the CI smoke test (both disabled) proves configuration without any network."""

    def probe(client, fn):
        if not client.enabled:
            return None
        try:
            fn()
            return True
        except (IntegrationUnavailable, IntegrationDisabled):
            return False

    mcp, rag = _mcp(), _rag()
    return jsonify(
        {
            "mcp": {"enabled": mcp.enabled, "url": mcp.url, "reachable": probe(mcp, mcp.list_tools)},
            "rag": {"enabled": rag.enabled, "url": rag.base_url, "reachable": probe(rag, rag.status)},
        }
    )


@bp.route("/tools")
def list_tools():
    """Tools registered on the shared MCP server (all features), flagged for ours."""

    try:
        return jsonify(_mcp().list_tools())
    except (IntegrationDisabled, IntegrationUnavailable) as exc:
        return _integration_error(exc, False)


@bp.route("/tools/run", methods=["POST"])
def run_tool():
    """Run one whitelisted Plant Health tool on the shared MCP server.

    Accepts JSON or form data: ``tool`` plus that tool's arguments. Returns the
    structured result as JSON, or a rendered fragment for HTMX.
    """

    wants_html = _wants_html()
    source = request.get_json(silent=True) or {} if request.is_json else request.form
    tool = (source.get("tool") or "").strip()
    try:
        if not tool:
            raise ValueError("Provide a 'tool' to run.")
        arguments = coerce_tool_args(tool, source)
        result = _mcp().call(tool, arguments)
    except (ValueError, IntegrationDisabled, IntegrationUnavailable) as exc:
        return _integration_error(exc, wants_html)

    if wants_html:
        return render_template("_mcp_result.html", result=result)
    return jsonify(result)


@bp.route("/ask", methods=["POST"])
def ask_records():
    """Ask the shared RAG server a question grounded in this service's records."""

    wants_html = _wants_html()
    source = request.get_json(silent=True) or {} if request.is_json else request.form
    try:
        question = _clean(source.get("question"), MAX_QUESTION_CHARS, "question")
        if not question:
            raise ValueError("Provide a question.")
        answer = _rag().ask(question, sources=("health",))
    except (ValueError, IntegrationDisabled, IntegrationUnavailable) as exc:
        return _integration_error(exc, wants_html)

    if wants_html:
        return render_template("_rag_answer.html", answer=answer)
    return jsonify(answer)


@bp.route("/ask/sync", methods=["POST"])
def sync_records():
    """Ask the shared RAG server to (re)index this service's assessments."""

    wants_html = _wants_html()
    try:
        result = _rag().sync_health()
    except (IntegrationDisabled, IntegrationUnavailable) as exc:
        return _integration_error(exc, wants_html, fragment="_notice.html")

    if wants_html:
        message = (
            f"Indexed {result.get('documents', 0)} record(s) as {result.get('chunks', 0)} passages"
            + (" with embeddings." if result.get("embedded") else ".")
        )
        return render_template("_notice.html", message=message, error=False, code=200)
    return jsonify(result)

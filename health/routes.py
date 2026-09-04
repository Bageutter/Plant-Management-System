import base64
import binascii
import json

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

from ai import AIUnavailableError
from extensions import db
from images import downscale_image, to_base64
from models import Assessment

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
        "ai": {"url": client.base_url, "model": client.model, "reachable": ai_up},
    }
    return jsonify(body), 200 if ai_up else 503


@bp.route("/")
def index():
    return render_template("index.html", recent=_recent())


@bp.route("/<int:assessment_id>")
def view_assessment(assessment_id):
    assessment = db.session.get(Assessment, assessment_id)
    if assessment is None:
        abort(404)
    return render_template(
        "detail.html", assessment=assessment, recent=_recent(exclude_id=assessment_id)
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
    db.session.commit()
    return assessment


@bp.route("/assessments", methods=["GET"])
def list_assessments():
    query = Assessment.query
    plant_ref = request.args.get("plant_ref")
    if plant_ref:
        query = query.filter_by(plant_ref=plant_ref)

    limit = request.args.get("limit", default=50, type=int)
    limit = max(1, min(limit, 200))

    assessments = (
        query.order_by(Assessment.created_at.desc(), Assessment.id.desc()).limit(limit).all()
    )
    return jsonify([a.to_dict() for a in assessments])


@bp.route("/assessments/<int:assessment_id>", methods=["GET"])
def get_assessment(assessment_id):
    assessment = db.session.get(Assessment, assessment_id)
    if assessment is None:
        return jsonify({"error": "assessment not found"}), 404
    return jsonify(assessment.to_dict())


MAX_NOTES_CHARS = 4000


def _apply_edit(assessment: Assessment, source) -> None:
    """Update the gardener-editable fields (plant_ref / description / notes).

    The AI assessment result itself is immutable — re-run an assessment to change
    it. `source` is `request.form` or a JSON dict.
    """
    if "plant_ref" in source:
        assessment.plant_ref = _clean(source.get("plant_ref"), MAX_PLANT_REF_CHARS, "plant_ref")
    if "description" in source:
        assessment.description = _clean(
            source.get("description"), MAX_DESCRIPTION_CHARS, "description"
        )
    if "notes" in source:
        assessment.notes = _clean(source.get("notes"), MAX_NOTES_CHARS, "notes")


@bp.route("/assessments/<int:assessment_id>/edit", methods=["POST"])
def edit_assessment(assessment_id):
    """Browser form: edit an assessment's plant name, description and notes."""
    assessment = db.session.get(Assessment, assessment_id)
    if assessment is None:
        abort(404)
    try:
        _apply_edit(assessment, request.form)
    except ValueError as exc:
        return _error(str(exc), 400, wants_html=True)
    db.session.commit()
    return redirect(url_for("health.view_assessment", assessment_id=assessment.id))


@bp.route("/assessments/<int:assessment_id>", methods=["PATCH", "PUT"])
def update_assessment(assessment_id):
    """JSON API: patch an assessment's gardener-editable fields."""
    assessment = db.session.get(Assessment, assessment_id)
    if assessment is None:
        return jsonify({"error": "assessment not found"}), 404
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "a JSON object body is required"}), 400
    try:
        _apply_edit(assessment, data)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    db.session.commit()
    return jsonify(assessment.to_dict())


@bp.route("/assessments/<int:assessment_id>", methods=["DELETE"])
def delete_assessment(assessment_id):
    assessment = db.session.get(Assessment, assessment_id)
    if assessment is None:
        return jsonify({"error": "assessment not found"}), 404

    db.session.delete(assessment)
    db.session.commit()
    return "", 204


@bp.route("/assessments/<int:assessment_id>/delete", methods=["POST"])
def delete_assessment_form(assessment_id):
    """Browser form: delete an assessment, then return to the index."""
    assessment = db.session.get(Assessment, assessment_id)
    if assessment is None:
        abort(404)
    db.session.delete(assessment)
    db.session.commit()
    return redirect(url_for("health.index"))


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
        raise ValueError("Image is too large")

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

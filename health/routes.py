import base64
import binascii

from flask import Blueprint, current_app, jsonify, render_template, request

from ai import AIUnavailableError
from extensions import db
from models import Assessment

bp = Blueprint("health", __name__)

MAX_DESCRIPTION_CHARS = 4000
MAX_PLANT_REF_CHARS = 200


def _client():
    return current_app.extensions["ollama"]


@bp.route("/")
def index():
    recent = (
        Assessment.query.order_by(Assessment.created_at.desc(), Assessment.id.desc())
        .limit(10)
        .all()
    )
    return render_template("index.html", recent=recent)


@bp.route("/healthz")
def healthz():
    client = _client()
    ai_up = client.ping()
    body = {
        "service": "health-monitoring-service",
        "status": "ok" if ai_up else "degraded",
        "ai": {"url": client.base_url, "model": client.model, "reachable": ai_up},
    }
    return jsonify(body), 200 if ai_up else 503


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

    assessment = Assessment.from_result(
        result,
        model=client.model,
        plant_ref=plant_ref,
        description=description,
        has_image=image_b64 is not None,
        image_mime=image_mime,
    )
    db.session.add(assessment)
    db.session.commit()

    if wants_html:
        return render_template("_assessment.html", assessment=assessment)
    return jsonify(assessment.to_dict()), 201


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


@bp.route("/assessments/<int:assessment_id>", methods=["DELETE"])
def delete_assessment(assessment_id):
    assessment = db.session.get(Assessment, assessment_id)
    if assessment is None:
        return jsonify({"error": "assessment not found"}), 404

    db.session.delete(assessment)
    db.session.commit()
    return "", 204


def _wants_html() -> bool:
    return request.headers.get("HX-Request") == "true" or (
        request.mimetype in {"multipart/form-data", "application/x-www-form-urlencoded"}
        and not request.is_json
    )


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

    return base64.b64encode(decoded).decode("ascii"), mime


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

    return base64.b64encode(payload).decode("ascii"), mime


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

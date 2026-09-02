from flask import Blueprint, current_app, render_template, request

from ai import AIUnavailableError
from auth_utils import require_garden_owner, require_login
from extensions import db
from models import Container, Garden, GardenArea, GardenChatMessage, Planting
from weather import WeatherUnavailableError

bp = Blueprint("garden_ai", __name__)

CHAT_HISTORY_LIMIT = 20
MAX_QUESTION_LENGTH = 500


def _get_owned_garden(garden_id: int) -> Garden:
    garden = db.session.get(Garden, garden_id)
    require_garden_owner(garden)
    return garden


def _history(garden_id: int) -> list[GardenChatMessage]:
    messages = (
        GardenChatMessage.query.filter_by(garden_id=garden_id)
        .order_by(GardenChatMessage.id.desc())
        .limit(CHAT_HISTORY_LIMIT)
        .all()
    )
    return list(reversed(messages))


def _render_chat(garden: Garden, error: str | None = None):
    return render_template(
        "_ai_history.html", garden=garden, messages=_history(garden.id), error=error
    )


def _planting_location(planting: Planting) -> str | None:
    location = planting.location
    if location is None:
        return None
    if location.garden_area is not None:
        return f"area: {location.garden_area.name}"
    if location.container is not None:
        return f"container: {location.container.name}"
    return None


def _weather_context(garden: Garden) -> dict | None:
    """Live weather for the garden's location, or None if it has no coordinates
    or Open-Meteo can't be reached (never blocks the chat)."""
    if garden.latitude is None or garden.longitude is None:
        return None
    try:
        return current_app.extensions["weather"].garden_weather(
            garden.latitude, garden.longitude
        )
    except WeatherUnavailableError:
        return None


def _garden_snapshot(garden: Garden) -> dict:
    areas = GardenArea.query.filter_by(garden_id=garden.id).order_by(GardenArea.name).all()
    containers = (
        Container.query.join(GardenArea, Container.garden_area_id == GardenArea.id)
        .filter(GardenArea.garden_id == garden.id)
        .order_by(Container.name)
        .all()
    )
    plantings = (
        Planting.query.filter_by(garden_id=garden.id).order_by(Planting.created_at.desc()).all()
    )
    return {
        "name": garden.name,
        "description": garden.description or None,
        "location_label": garden.location_label or None,
        "climate_zone": garden.climate_zone or None,
        "coordinates": (
            {"latitude": garden.latitude, "longitude": garden.longitude}
            if garden.latitude is not None and garden.longitude is not None
            else None
        ),
        "weather": _weather_context(garden),
        "areas": [
            {"name": a.name, "type": a.area_type, "notes": a.notes} for a in areas
        ],
        "containers": [
            {"name": c.name, "type": c.container_type, "area": c.garden_area.name}
            for c in containers
        ],
        "plantings": [
            {
                "crop_name": p.crop_name,
                "quantity": p.quantity,
                "lifecycle_state": p.lifecycle_state,
                "growth_stage": p.growth_stage,
                "planted_date": p.planted_date.isoformat() if p.planted_date else None,
                "expected_harvest_date": (
                    p.expected_harvest_date.isoformat() if p.expected_harvest_date else None
                ),
                "location": _planting_location(p),
            }
            for p in plantings
        ],
    }


@bp.route("/gardens/<int:garden_id>/ai/ask", methods=["POST"])
@require_login
def ask(garden_id):
    garden = _get_owned_garden(garden_id)

    question = (request.form.get("question") or "").strip()
    if not question:
        return _render_chat(garden, "Enter a question first."), 400
    if len(question) > MAX_QUESTION_LENGTH:
        return _render_chat(garden, f"Keep your question under {MAX_QUESTION_LENGTH} characters."), 400

    history = [{"role": m.role, "content": m.content} for m in _history(garden_id)]
    try:
        result = current_app.extensions["garden_ai"].ask(
            question, _garden_snapshot(garden), history
        )
    except AIUnavailableError:
        return _render_chat(
            garden,
            "The local AI model is unavailable. Check that Ollama is running and try again.",
        ), 503

    db.session.add_all(
        [
            GardenChatMessage(garden_id=garden_id, role="user", content=question),
            GardenChatMessage(garden_id=garden_id, role="assistant", content=result["answer"]),
        ]
    )
    db.session.commit()
    return _render_chat(garden)


@bp.route("/gardens/<int:garden_id>/ai/clear", methods=["POST"])
@require_login
def clear(garden_id):
    garden = _get_owned_garden(garden_id)
    GardenChatMessage.query.filter_by(garden_id=garden_id).delete()
    db.session.commit()
    return _render_chat(garden)

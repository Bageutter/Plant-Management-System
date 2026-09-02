from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from auth_utils import require_garden_owner, require_login
from extensions import db
from form_helpers import parse_date, parse_float, parse_int
from models import LIFECYCLE_STATES, Container, Garden, GardenArea, Planting, PlantingLocation

bp = Blueprint("plantings", __name__)


def _get_owned_garden(garden_id):
    garden = db.session.get(Garden, garden_id)
    require_garden_owner(garden)
    return garden


def _resolve_location(garden_id: int) -> tuple[GardenArea | None, Container | None, str | None]:
    """Read area/container choice from the form. Returns (area, container, error)."""
    area_id = request.form.get("garden_area_id", type=int)
    container_id = request.form.get("container_id", type=int)

    if bool(area_id) == bool(container_id):
        return None, None, "Choose exactly one location: a garden area or a container."

    if area_id:
        area = GardenArea.query.filter_by(id=area_id, garden_id=garden_id).first()
        if area is None:
            return None, None, "That garden area wasn't found."
        return area, None, None

    container = (
        Container.query.join(GardenArea, Container.garden_area_id == GardenArea.id)
        .filter(Container.id == container_id, GardenArea.garden_id == garden_id)
        .first()
    )
    if container is None:
        return None, None, "That container wasn't found."
    return None, container, None


def _apply_planting_form(planting: Planting) -> str | None:
    crop_name = (request.form.get("crop_name") or "").strip()
    lifecycle_state = request.form.get("lifecycle_state") or "planned"

    if not crop_name:
        return "Crop name is required."
    if lifecycle_state not in LIFECYCLE_STATES:
        return "Invalid lifecycle state."

    planting.crop_name = crop_name
    planting.quantity = parse_int(request.form.get("quantity"), 1) or 1
    planting.lifecycle_state = lifecycle_state
    planting.growth_stage = (request.form.get("growth_stage") or "").strip() or None
    planting.planted_date = parse_date(request.form.get("planted_date"))
    planting.expected_harvest_date = parse_date(request.form.get("expected_harvest_date"))
    planting.actual_harvest_date = parse_date(request.form.get("actual_harvest_date"))
    planting.notes = (request.form.get("notes") or "").strip() or None
    return None


@bp.route("/gardens/<int:garden_id>/plantings", methods=["POST"])
@require_login
def create_planting(garden_id):
    _get_owned_garden(garden_id)

    area, container, error = _resolve_location(garden_id)
    planting = Planting(garden_id=garden_id)
    if error is None:
        error = _apply_planting_form(planting)

    if error:
        flash(error, "error")
        return redirect(url_for("gardens.view_garden", garden_id=garden_id))

    db.session.add(planting)
    db.session.flush()  # assign planting.id before creating its location

    location = PlantingLocation(
        planting_id=planting.id,
        garden_area_id=area.id if area else None,
        container_id=container.id if container else None,
        pos_x=parse_float(request.form.get("pos_x"), 0.0),
        pos_y=parse_float(request.form.get("pos_y"), 0.0),
    )
    db.session.add(location)
    db.session.commit()

    flash(f'Added planting "{planting.crop_name}".', "success")
    return redirect(url_for("gardens.view_garden", garden_id=garden_id))


@bp.route("/gardens/<int:garden_id>/plantings/<int:planting_id>")
@require_login
def view_planting(garden_id, planting_id):
    garden = _get_owned_garden(garden_id)
    planting = Planting.query.filter_by(id=planting_id, garden_id=garden_id).first()
    if planting is None:
        abort(404)

    areas = GardenArea.query.filter_by(garden_id=garden_id).order_by(GardenArea.name).all()
    containers = (
        Container.query.join(GardenArea, Container.garden_area_id == GardenArea.id)
        .filter(GardenArea.garden_id == garden_id)
        .order_by(Container.name)
        .all()
    )
    return render_template(
        "planting_detail.html", garden=garden, planting=planting, areas=areas, containers=containers
    )


@bp.route("/gardens/<int:garden_id>/plantings/<int:planting_id>/edit", methods=["POST"])
@require_login
def edit_planting(garden_id, planting_id):
    _get_owned_garden(garden_id)
    planting = Planting.query.filter_by(id=planting_id, garden_id=garden_id).first()
    if planting is None:
        abort(404)

    area, container, error = _resolve_location(garden_id)
    if error is None:
        error = _apply_planting_form(planting)

    if error:
        flash(error, "error")
        return redirect(url_for("plantings.view_planting", garden_id=garden_id, planting_id=planting_id))

    planting.location.garden_area_id = area.id if area else None
    planting.location.container_id = container.id if container else None
    planting.location.pos_x = parse_float(request.form.get("pos_x"), 0.0)
    planting.location.pos_y = parse_float(request.form.get("pos_y"), 0.0)
    db.session.commit()

    flash("Planting updated.", "success")
    return redirect(url_for("plantings.view_planting", garden_id=garden_id, planting_id=planting_id))


@bp.route("/gardens/<int:garden_id>/plantings/<int:planting_id>/delete", methods=["POST"])
@require_login
def delete_planting(garden_id, planting_id):
    _get_owned_garden(garden_id)
    planting = Planting.query.filter_by(id=planting_id, garden_id=garden_id).first()
    if planting is None:
        abort(404)

    crop_name = planting.crop_name
    db.session.delete(planting)
    db.session.commit()
    flash(f'Deleted planting "{crop_name}".', "success")
    return redirect(url_for("gardens.view_garden", garden_id=garden_id))

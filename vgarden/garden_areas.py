from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from auth_utils import require_garden_owner, require_login
from extensions import db
from form_helpers import parse_float
from models import AREA_TYPES, Garden, GardenArea, Planting, PlantingLocation

bp = Blueprint("garden_areas", __name__)


def _get_owned_garden(garden_id):
    garden = db.session.get(Garden, garden_id)
    require_garden_owner(garden)
    return garden


def _delete_plantings_in_area(area: GardenArea) -> None:
    """Explicitly delete plantings located in this area (or in one of its containers).

    Planting isn't a child of GardenArea/Container in the ORM graph (it only owns its
    PlantingLocation), so the area's own delete-orphan cascade would silently orphan
    these plantings - it deletes their PlantingLocation row but not the Planting itself.
    """
    container_ids = [c.id for c in area.containers]
    conditions = [PlantingLocation.garden_area_id == area.id]
    if container_ids:
        conditions.append(PlantingLocation.container_id.in_(container_ids))

    plantings = Planting.query.join(PlantingLocation).filter(db.or_(*conditions)).all()
    for planting in plantings:
        db.session.delete(planting)


def _apply_form(area: GardenArea) -> str | None:
    """Populate area from request.form; return an error message, or None on success."""
    name = (request.form.get("name") or "").strip()
    area_type = request.form.get("area_type") or "bed"

    if not name:
        return "Name is required."
    if area_type not in AREA_TYPES:
        return "Invalid area type."

    area.name = name
    area.area_type = area_type
    area.pos_x = parse_float(request.form.get("pos_x"), 0.0)
    area.pos_y = parse_float(request.form.get("pos_y"), 0.0)
    area.width = parse_float(request.form.get("width"), 1.0)
    area.length = parse_float(request.form.get("length"), 1.0)
    area.notes = (request.form.get("notes") or "").strip() or None
    return None


@bp.route("/gardens/<int:garden_id>/areas", methods=["POST"])
@require_login
def create_area(garden_id):
    _get_owned_garden(garden_id)

    area = GardenArea(garden_id=garden_id)
    error = _apply_form(area)
    if error:
        flash(error, "error")
        return redirect(url_for("gardens.view_garden", garden_id=garden_id))

    db.session.add(area)
    db.session.commit()
    flash(f'Added area "{area.name}".', "success")
    return redirect(url_for("gardens.view_garden", garden_id=garden_id))


@bp.route("/gardens/<int:garden_id>/areas/<int:area_id>")
@require_login
def view_area(garden_id, area_id):
    garden = _get_owned_garden(garden_id)
    area = GardenArea.query.filter_by(id=area_id, garden_id=garden_id).first()
    if area is None:
        abort(404)
    return render_template("area_detail.html", garden=garden, area=area)


@bp.route("/gardens/<int:garden_id>/areas/<int:area_id>/edit", methods=["POST"])
@require_login
def edit_area(garden_id, area_id):
    _get_owned_garden(garden_id)
    area = GardenArea.query.filter_by(id=area_id, garden_id=garden_id).first()
    if area is None:
        abort(404)

    error = _apply_form(area)
    if error:
        flash(error, "error")
        return redirect(url_for("garden_areas.view_area", garden_id=garden_id, area_id=area_id))

    db.session.commit()
    flash("Area updated.", "success")
    return redirect(url_for("garden_areas.view_area", garden_id=garden_id, area_id=area_id))


@bp.route("/gardens/<int:garden_id>/areas/<int:area_id>/delete", methods=["POST"])
@require_login
def delete_area(garden_id, area_id):
    _get_owned_garden(garden_id)
    area = GardenArea.query.filter_by(id=area_id, garden_id=garden_id).first()
    if area is None:
        abort(404)

    name = area.name
    _delete_plantings_in_area(area)
    db.session.delete(area)
    db.session.commit()
    flash(f'Deleted area "{name}".', "success")
    return redirect(url_for("gardens.view_garden", garden_id=garden_id))

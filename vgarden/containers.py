from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from auth_utils import require_garden_owner, require_login
from extensions import db
from form_helpers import parse_float
from models import CONTAINER_TYPES, Container, Garden, GardenArea, Planting, PlantingLocation

bp = Blueprint("containers", __name__)


def _get_owned_garden(garden_id):
    garden = db.session.get(Garden, garden_id)
    require_garden_owner(garden)
    return garden


def _apply_form(container: Container, garden_id: int) -> str | None:
    name = (request.form.get("name") or "").strip()
    container_type = request.form.get("container_type") or "pot"
    garden_area_id = request.form.get("garden_area_id", type=int)

    if not name:
        return "Name is required."
    if container_type not in CONTAINER_TYPES:
        return "Invalid container type."
    area = GardenArea.query.filter_by(id=garden_area_id, garden_id=garden_id).first()
    if area is None:
        return "Choose a garden area for this container."

    container.name = name
    container.container_type = container_type
    container.garden_area_id = area.id
    container.pos_x = parse_float(request.form.get("pos_x"), 0.0)
    container.pos_y = parse_float(request.form.get("pos_y"), 0.0)
    container.width = parse_float(request.form.get("width"))
    container.depth = parse_float(request.form.get("depth"))
    container.height = parse_float(request.form.get("height"))
    container.volume_liters = parse_float(request.form.get("volume_liters"))
    return None


@bp.route("/gardens/<int:garden_id>/containers", methods=["POST"])
@require_login
def create_container(garden_id):
    _get_owned_garden(garden_id)

    container = Container()
    error = _apply_form(container, garden_id)
    if error:
        flash(error, "error")
        return redirect(url_for("gardens.view_garden", garden_id=garden_id))

    db.session.add(container)
    db.session.commit()
    flash(f'Added container "{container.name}".', "success")
    return redirect(url_for("gardens.view_garden", garden_id=garden_id))


def _get_container_in_garden(garden_id, container_id):
    return (
        Container.query.join(GardenArea, Container.garden_area_id == GardenArea.id)
        .filter(Container.id == container_id, GardenArea.garden_id == garden_id)
        .first()
    )


@bp.route("/gardens/<int:garden_id>/containers/<int:container_id>")
@require_login
def view_container(garden_id, container_id):
    garden = _get_owned_garden(garden_id)
    container = _get_container_in_garden(garden_id, container_id)
    if container is None:
        abort(404)
    return render_template("container_detail.html", garden=garden, container=container)


@bp.route("/gardens/<int:garden_id>/containers/<int:container_id>/edit", methods=["POST"])
@require_login
def edit_container(garden_id, container_id):
    _get_owned_garden(garden_id)
    container = _get_container_in_garden(garden_id, container_id)
    if container is None:
        abort(404)

    error = _apply_form(container, garden_id)
    if error:
        flash(error, "error")
        return redirect(url_for("containers.view_container", garden_id=garden_id, container_id=container_id))

    db.session.commit()
    flash("Container updated.", "success")
    return redirect(url_for("containers.view_container", garden_id=garden_id, container_id=container_id))


@bp.route("/gardens/<int:garden_id>/containers/<int:container_id>/delete", methods=["POST"])
@require_login
def delete_container(garden_id, container_id):
    _get_owned_garden(garden_id)
    container = _get_container_in_garden(garden_id, container_id)
    if container is None:
        abort(404)

    name = container.name
    # Explicitly delete plantings in this container - see the equivalent comment in
    # garden_areas.py's _delete_plantings_in_area; the container's own cascade would
    # otherwise silently orphan them.
    plantings = Planting.query.join(PlantingLocation).filter(PlantingLocation.container_id == container.id).all()
    for planting in plantings:
        db.session.delete(planting)
    db.session.delete(container)
    db.session.commit()
    flash(f'Deleted container "{name}".', "success")
    return redirect(url_for("gardens.view_garden", garden_id=garden_id))

from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from auth_utils import require_garden_owner, require_login, require_service_token, verify_sso_token
from extensions import csrf, db
from form_helpers import parse_float
from models import Container, Garden, GardenArea, Planting

bp = Blueprint("gardens", __name__)


@bp.route("/healthz")
def healthz():
    return jsonify({"status": "ok", "service": "vgarden"})


# --- Browser-facing ---


@bp.route("/sso")
def sso():
    """Land here from auth's SSO handoff: verify the token, start a vgarden session."""
    next_path = request.args.get("next", "/")
    if not next_path.startswith("/") or next_path.startswith("//"):
        next_path = "/"

    data = verify_sso_token(request.args.get("token", ""))
    if data is None:
        return redirect(f"{current_app.config['AUTH_PUBLIC_URL']}/login")

    session["user_id"] = data["user_id"]
    session["email"] = data.get("email")
    session.permanent = True
    # next_path is app-relative (e.g. /gardens/1/view). Behind the proxy, prepend
    # this service's mount prefix so the browser lands back on /vgarden/...
    return redirect(request.script_root + next_path)


@bp.route("/gardens/<int:garden_id>/view")
@require_login
def view_garden(garden_id):
    garden = db.session.get(Garden, garden_id)
    if garden is None:
        return render_template("garden_not_found.html"), 404
    require_garden_owner(garden)

    areas = GardenArea.query.filter_by(garden_id=garden_id).order_by(GardenArea.name).all()
    containers = (
        Container.query.join(GardenArea, Container.garden_area_id == GardenArea.id)
        .filter(GardenArea.garden_id == garden_id)
        .order_by(Container.name)
        .all()
    )
    plantings = (
        Planting.query.filter_by(garden_id=garden_id).order_by(Planting.created_at.desc()).all()
    )

    return render_template(
        "garden_view.html", garden=garden, areas=areas, containers=containers, plantings=plantings
    )


@bp.route("/gardens/<int:garden_id>/edit", methods=["POST"])
@require_login
def edit_garden(garden_id):
    garden = db.session.get(Garden, garden_id)
    if garden is None:
        return render_template("garden_not_found.html"), 404
    require_garden_owner(garden)

    name = (request.form.get("name") or "").strip()
    if not name:
        flash("Garden name is required.", "error")
        return redirect(url_for("gardens.view_garden", garden_id=garden_id))

    garden.name = name
    garden.description = (request.form.get("description") or "").strip()
    garden.location_label = (request.form.get("location_label") or "").strip()
    garden.climate_zone = (request.form.get("climate_zone") or "").strip()
    garden.latitude = parse_float(request.form.get("latitude"))
    garden.longitude = parse_float(request.form.get("longitude"))
    garden.map_width_m = parse_float(request.form.get("map_width_m"), garden.map_width_m)
    garden.map_height_m = parse_float(request.form.get("map_height_m"), garden.map_height_m)
    db.session.commit()

    flash("Garden info updated.", "success")
    return redirect(url_for("gardens.view_garden", garden_id=garden_id))


# --- Server-to-server (called by auth), bearer-token authenticated ---


@bp.route("/gardens", methods=["POST"])
@csrf.exempt
@require_service_token
def create_garden():
    data = request.get_json(silent=True) or {}
    owner_id = data.get("owner_id")
    name = data.get("name")

    if not isinstance(owner_id, int):
        return jsonify({"error": "owner_id (integer) is required"}), 400
    if not isinstance(name, str) or not name.strip():
        return jsonify({"error": "name (non-empty string) is required"}), 400

    name = name.strip()
    if len(name) > 120:
        return jsonify({"error": "name must be 120 characters or fewer"}), 400

    garden = Garden(owner_id=owner_id, name=name)
    db.session.add(garden)
    db.session.commit()
    return jsonify(garden.to_dict()), 201


@bp.route("/gardens", methods=["GET"])
@require_service_token
def list_gardens():
    owner_id = request.args.get("owner_id", type=int)
    query = Garden.query
    if owner_id is not None:
        query = query.filter_by(owner_id=owner_id)
    gardens = query.order_by(Garden.created_at).all()
    return jsonify([g.to_dict() for g in gardens])


@bp.route("/gardens/<int:garden_id>", methods=["GET"])
@require_service_token
def get_garden(garden_id):
    garden = db.session.get(Garden, garden_id)
    if garden is None:
        return jsonify({"error": "garden not found"}), 404
    return jsonify(garden.to_dict())


@bp.route("/gardens/<int:garden_id>", methods=["DELETE"])
@csrf.exempt
@require_service_token
def delete_garden(garden_id):
    garden = db.session.get(Garden, garden_id)
    if garden is None:
        return jsonify({"error": "garden not found"}), 404

    db.session.delete(garden)
    db.session.commit()
    return "", 204

from flask import Blueprint, jsonify, render_template, request

from extensions import db
from models import Garden

bp = Blueprint("gardens", __name__)


@bp.route("/gardens/<int:garden_id>/view")
def view_garden(garden_id):
    garden = db.session.get(Garden, garden_id)
    if garden is None:
        return render_template("garden_not_found.html"), 404
    return render_template("garden_view.html", garden=garden)


@bp.route("/gardens", methods=["POST"])
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
def list_gardens():
    owner_id = request.args.get("owner_id", type=int)
    query = Garden.query
    if owner_id is not None:
        query = query.filter_by(owner_id=owner_id)
    gardens = query.order_by(Garden.created_at).all()
    return jsonify([g.to_dict() for g in gardens])


@bp.route("/gardens/<int:garden_id>", methods=["GET"])
def get_garden(garden_id):
    garden = db.session.get(Garden, garden_id)
    if garden is None:
        return jsonify({"error": "garden not found"}), 404
    return jsonify(garden.to_dict())


@bp.route("/gardens/<int:garden_id>", methods=["DELETE"])
def delete_garden(garden_id):
    garden = db.session.get(Garden, garden_id)
    if garden is None:
        return jsonify({"error": "garden not found"}), 404

    db.session.delete(garden)
    db.session.commit()
    return "", 204

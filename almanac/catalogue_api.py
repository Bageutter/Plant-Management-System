"""Public, read-only catalogue views used by the MCP adapter and other services."""

from copy import deepcopy

from flask import Blueprint, jsonify, request, url_for
from sqlalchemy import func, literal, or_, select, union_all

from extensions import db
from models import Disease, Pest, PlantReference
from planning import calculate
from problem_guides import DISEASE_GUIDES, PEST_GUIDES


catalogue_api = Blueprint("catalogue_api", __name__, url_prefix="/api/catalogue")
KINDS = {"plant": PlantReference, "pest": Pest, "disease": Disease}


def pagination():
    try:
        limit = int(request.args.get("limit", "20"))
        offset = int(request.args.get("offset", "0"))
    except ValueError:
        raise ValueError("limit and offset must be integers") from None
    if not 1 <= limit <= 50 or not 0 <= offset <= 100000:
        raise ValueError("limit must be 1–50; offset must be 0–100000")
    return limit, offset


def reference(kind, record):
    key = record.slug if kind == "plant" else str(record.id)
    plural = {"plant": "plants", "pest": "pests", "disease": "diseases"}[kind]
    endpoint = f"{kind}_detail"
    values = {"slug": key} if kind == "plant" else {f"{kind}_id": record.id}
    return {
        "kind": kind,
        "id": record.id,
        "key": key,
        "name": record.common_name if kind == "plant" else record.name,
        "uri": f"almanac://{plural}/{key}",
        "path": url_for(endpoint, **values),
    }


@catalogue_api.errorhandler(ValueError)
def invalid_input(error):
    return jsonify(error=str(error)), 400


@catalogue_api.get("")
def search():
    """One bounded, stable search across the three public reference tables."""
    kind = request.args.get("kind", "all")
    if kind not in (*KINDS, "all"):
        raise ValueError("kind must be plant, pest, disease, or all")
    query = request.args.get("q", "").strip()
    if len(query) > 120:
        raise ValueError("q must be at most 120 characters")
    limit, offset = pagination()
    queries = []
    for item_kind, model in KINDS.items():
        if kind != "all" and kind != item_kind:
            continue
        name = model.common_name if item_kind == "plant" else model.name
        statement = select(literal(item_kind).label("kind"), model.id, name.label("name"))
        if query:
            columns = [name]
            if item_kind == "plant":
                columns += [model.scientific_name, model.slug]
            statement = statement.where(
                or_(
                    *[
                        func.lower(column).contains(query.lower(), autoescape=True)
                        for column in columns
                    ]
                )
            )
        queries.append(statement)
    combined = union_all(*queries).subquery()
    total = db.session.scalar(select(func.count()).select_from(combined))
    rows = db.session.execute(
        select(combined)
        .order_by(func.lower(combined.c.name), combined.c.kind, combined.c.id)
        .limit(limit)
        .offset(offset)
    )
    items = [reference(row.kind, db.session.get(KINDS[row.kind], row.id)) for row in rows]
    return jsonify(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
        next_offset=offset + limit if offset + limit < total else None,
    )


@catalogue_api.get("/plant/<slug>")
def plant(slug):
    record = PlantReference.query.filter_by(slug=slug).first()
    if record is None:
        return jsonify(error="Plant not found; search the catalogue for a valid slug."), 404
    return jsonify(
        **reference("plant", record),
        record=record.to_dict(),
        pests=[reference("pest", item) for item in sorted(record.pests, key=lambda p: p.name)],
        diseases=[
            reference("disease", item) for item in sorted(record.diseases, key=lambda p: p.name)
        ],
        evidence_note="Fields in estimated_fields are estimates, not measured or verified facts.",
    )


@catalogue_api.get("/<kind>/<int:record_id>")
def problem(kind, record_id):
    if kind not in ("pest", "disease"):
        return jsonify(error="Problem kind must be pest or disease."), 400
    record = db.session.get(KINDS[kind], record_id)
    if record is None:
        return jsonify(error="Problem not found; search the catalogue for a valid ID."), 404
    limit, offset = pagination()
    related = PlantReference.query.filter(getattr(PlantReference, f"{kind}s").any(id=record.id))
    total = related.count()
    plants = (
        related.order_by(PlantReference.common_name, PlantReference.id).limit(limit).offset(offset)
    )
    guides = PEST_GUIDES if kind == "pest" else DISEASE_GUIDES
    guide = deepcopy(guides.get(record.name))
    if guide:
        for companion in guide.get("companions", []):
            linked = PlantReference.query.filter_by(slug=companion.get("slug")).first()
            if linked:
                companion["plant"] = reference("plant", linked)
    return jsonify(
        **reference(kind, record),
        description=record.description,
        guide=guide,
        guide_available=guide is not None,
        plants=[reference("plant", item) for item in plants],
        total_plants=total,
        limit=limit,
        offset=offset,
        next_offset=offset + limit if offset + limit < total else None,
        evidence_note="Recorded plant links are catalogue associations, not confirmed diagnoses. "
        "A missing guide means management guidance is not available in this catalogue.",
    )


@catalogue_api.get("/plant/<slug>/calculate")
def harvest(slug):
    record = PlantReference.query.filter_by(slug=slug).first()
    if record is None:
        return jsonify(error="Plant not found; search the catalogue for a valid slug."), 404
    result = calculate(record, request.args.get("amount"), request.args.get("unit", ""))
    return jsonify(
        **reference("plant", record),
        calculation=result,
        estimated_fields=record.estimated_fields or [],
        evidence_note="A planning estimate based on recorded yield and spacing; not a harvest guarantee.",
    )

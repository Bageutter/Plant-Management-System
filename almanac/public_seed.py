"""Import the public My Garden catalogue without replacing local plant records."""

from __future__ import annotations

import json
from urllib import request

from extensions import db
from models import (
    Disease,
    Pest,
    PlantCompanion,
    PlantImage,
    PlantFunctionTag,
    PlantReference,
    PlantUse,
    PlantingMonth,
    RotationGroup,
)


SUPPORTED_SNAPSHOT_FORMAT = 1

PLANT_FIELDS = (
    "slug", "common_name", "scientific_name", "family", "summary",
    "yield_qty", "in_row_spacing_cm", "row_spacing_cm",
    "succession_interval_days", "harvest_window_weeks", "soil_ph_min",
    "soil_ph_max", "yield_wording", "yield_unit", "management_notes",
    "care_notes", "uses_notes", "sowing_notes", "source_url",
    "feeder_type", "water_needs", "sun_needs", "forest_layer", "part_used",
)


def fetch_snapshot(url: str, timeout: int = 10) -> dict:
    """Fetch a versioned public snapshot without sending credentials."""
    req = request.Request(url, headers={"User-Agent": "Plant-Management-System/1"})
    with request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


def _named_records(
    rows: list[dict], model, fields: tuple[str, ...], *, preserve_existing: bool = False
) -> dict[int, object]:
    records = {}
    for row in rows:
        record = model.query.filter_by(name=row["name"]).first()
        existing = record is not None
        if record is None:
            record = model(name=row["name"])
            db.session.add(record)
        for field in fields:
            if not (preserve_existing and existing) or getattr(record, field) in (None, ""):
                setattr(record, field, row.get(field))
        records[row["id"]] = record
    return records


def import_snapshot(
    snapshot: dict, public_image_base_url: str | None = None, *, add_missing: bool = False
) -> int:
    """Seed an empty database, or explicitly fill gaps without replacing local data."""
    if not add_missing and PlantReference.query.first() is not None:
        return 0
    if snapshot.get("snapshot_format") != SUPPORTED_SNAPSHOT_FORMAT:
        raise ValueError("Unsupported My Garden snapshot format.")
    tables = snapshot.get("tables")
    if not isinstance(tables, dict) or not isinstance(tables.get("plant_references"), list):
        raise ValueError("My Garden snapshot is missing catalogue tables.")

    rotation_groups = _named_records(
        tables.get("rotation_groups", []), RotationGroup,
        ("feeder_weight", "is_rotation_exempt"),
        preserve_existing=add_missing,
    )
    pests = _named_records(
        tables.get("pests", []), Pest, ("description",), preserve_existing=add_missing
    )
    diseases = _named_records(
        tables.get("diseases", []), Disease, ("description",), preserve_existing=add_missing
    )
    functions = _named_records(
        tables.get("function_tags", []), PlantFunctionTag, ("description",),
        preserve_existing=add_missing,
    )
    uses = _named_records(
        tables.get("uses", []), PlantUse, ("description",), preserve_existing=add_missing
    )

    plants = {}
    added = set()
    for row in tables["plant_references"]:
        existing = PlantReference.query.filter_by(slug=row["slug"]).first()
        if existing is not None:
            for field in PLANT_FIELDS:
                if getattr(existing, field) in (None, ""):
                    setattr(existing, field, row.get(field))
            if existing.rotation_group is None and row.get("rotation_group_id") is not None:
                existing.rotation_group = rotation_groups[row["rotation_group_id"]]
            plants[row["id"]] = existing
            continue
        plant = PlantReference(**{field: row.get(field) for field in PLANT_FIELDS})
        if row.get("rotation_group_id") is not None:
            plant.rotation_group = rotation_groups[row["rotation_group_id"]]
        db.session.add(plant)
        plants[row["id"]] = plant
        added.add(row["id"])
    db.session.flush()

    for row in tables.get("planting_months", []):
        plant = plants[row["plant_reference_id"]]
        if row["month_number"] in {month.month_number for month in plant.planting_months}:
            continue
        plant.planting_months.append(PlantingMonth(month_number=row["month_number"]))
    for table_name, records, attribute in (
        ("plant_pests", pests, "pests"),
        ("plant_diseases", diseases, "diseases"),
        ("plant_function_tags", functions, "function_tags"),
        ("plant_uses", uses, "uses"),
    ):
        for row in tables.get(table_name, []):
            linked = getattr(plants[row["plant_id"]], attribute)
            record = records[row["tag_id"]]
            if record not in linked:
                linked.append(record)
    for row in tables.get("plant_companions", []):
        key = (
            plants[row["plant_id"]].id,
            plants[row["companion_id"]].id,
            functions[row["function_id"]].id,
        )
        if db.session.get(PlantCompanion, key) is not None:
            continue
        db.session.add(
            PlantCompanion(
                plant_id=key[0], companion_id=key[1], function_id=key[2],
                notes=row.get("notes"),
            )
        )

    if public_image_base_url:
        for row in tables.get("plant_images", []):
            filename = row.get("filename")
            plant = plants.get(row.get("plant_reference_id"))
            if plant is not None and plant.image is None and isinstance(filename, str) and filename:
                plant.image = PlantImage(
                    filename=filename,
                    public_url=f"{public_image_base_url.rstrip('/')}/{filename}",
                )

    db.session.commit()
    return len(added)

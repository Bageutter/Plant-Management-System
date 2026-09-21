"""Import the public My Garden catalogue into a brand-new Almanac database."""

from __future__ import annotations

import json
from urllib import request

from extensions import db
from models import (
    Disease,
    Pest,
    PlantCompanion,
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


def _named_records(rows: list[dict], model, fields: tuple[str, ...]) -> dict[int, object]:
    records = {}
    for row in rows:
        record = model.query.filter_by(name=row["name"]).first()
        if record is None:
            record = model(name=row["name"])
            db.session.add(record)
        for field in fields:
            setattr(record, field, row.get(field))
        records[row["id"]] = record
    return records


def import_snapshot(snapshot: dict) -> int:
    """Copy a public snapshot into an empty database without later overwrites."""
    if PlantReference.query.first() is not None:
        return 0
    if snapshot.get("snapshot_format") != SUPPORTED_SNAPSHOT_FORMAT:
        raise ValueError("Unsupported My Garden snapshot format.")
    tables = snapshot.get("tables")
    if not isinstance(tables, dict) or not isinstance(tables.get("plant_references"), list):
        raise ValueError("My Garden snapshot is missing catalogue tables.")

    rotation_groups = _named_records(
        tables.get("rotation_groups", []), RotationGroup,
        ("feeder_weight", "is_rotation_exempt"),
    )
    pests = _named_records(tables.get("pests", []), Pest, ("description",))
    diseases = _named_records(tables.get("diseases", []), Disease, ("description",))
    functions = _named_records(
        tables.get("function_tags", []), PlantFunctionTag, ("description",)
    )
    uses = _named_records(tables.get("uses", []), PlantUse, ("description",))

    plants = {}
    for row in tables["plant_references"]:
        plant = PlantReference(**{field: row.get(field) for field in PLANT_FIELDS})
        if row.get("rotation_group_id") is not None:
            plant.rotation_group = rotation_groups[row["rotation_group_id"]]
        db.session.add(plant)
        plants[row["id"]] = plant
    db.session.flush()

    for row in tables.get("planting_months", []):
        plants[row["plant_reference_id"]].planting_months.append(
            PlantingMonth(month_number=row["month_number"])
        )
    for table_name, records, attribute in (
        ("plant_pests", pests, "pests"),
        ("plant_diseases", diseases, "diseases"),
        ("plant_function_tags", functions, "function_tags"),
        ("plant_uses", uses, "uses"),
    ):
        for row in tables.get(table_name, []):
            getattr(plants[row["plant_id"]], attribute).append(records[row["tag_id"]])
    for row in tables.get("plant_companions", []):
        db.session.add(
            PlantCompanion(
                plant_id=plants[row["plant_id"]].id,
                companion_id=plants[row["companion_id"]].id,
                function_id=functions[row["function_id"]].id,
                notes=row.get("notes"),
            )
        )

    db.session.commit()
    return len(plants)

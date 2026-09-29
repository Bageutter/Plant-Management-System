"""Validated growing-knowledge catalogue edits."""

import math
from catalogue import CHOICES, NUMERIC, TEXT
from extensions import db
from models import Disease, Pest, PlantFunctionTag, PlantUse, RotationGroup

RELATIONS = {
    "pests": Pest,
    "diseases": Disease,
    "function_tags": PlantFunctionTag,
    "uses": PlantUse,
}


def parse_details(form):
    fields = {}
    for key in [*NUMERIC, *TEXT, *CHOICES, "rotation_group_id"]:
        if key not in form:
            continue  # Older clients preserve fields they do not send.
        raw = str(form.get(key) or "").strip()
        fields[key] = raw or None
        if not raw:
            continue
        if key in NUMERIC or key == "rotation_group_id":
            try:
                value = float(raw)
            except ValueError:
                raise ValueError(
                    f"{NUMERIC.get(key, 'Rotation group')} must be a number."
                ) from None
            if not math.isfinite(value):
                raise ValueError("Enter finite numbers only.")
            if key.startswith("soil_ph"):
                if not 0 <= value <= 14:
                    raise ValueError("Soil pH must be between 0 and 14.")
            elif value <= 0:
                raise ValueError("Yield, spacing and intervals must be greater than zero.")
            if key in ("succession_interval_days", "rotation_group_id"):
                if not value.is_integer():
                    raise ValueError("Days and rotation group must be whole numbers.")
                value = int(value)
            if key == "rotation_group_id" and not db.session.get(RotationGroup, value):
                raise ValueError("Choose an existing rotation group.")
            fields[key] = value
        elif key in CHOICES and raw not in CHOICES[key]:
            raise ValueError(f"Choose a valid {key.replace('_', ' ')}.")
    if (
        fields.get("soil_ph_min") is not None
        and fields.get("soil_ph_max") is not None
        and fields["soil_ph_min"] > fields["soil_ph_max"]
    ):
        raise ValueError("Minimum soil pH cannot exceed maximum soil pH.")
    if "yield_qty" in fields or "yield_unit" in fields:
        if bool(fields.get("yield_qty")) != bool(fields.get("yield_unit")):
            raise ValueError("Enter both yield quantity and unit, or leave both blank.")
    for key, model in RELATIONS.items():
        if f"{key}_present" not in form:
            continue
        values = form.getlist(key)
        if key in ("pests", "diseases"):
            values = [name.strip() for name in form.get(key, "").split(",") if name.strip()]
            if any(len(v) > 100 for v in values):
                raise ValueError("Pest and disease names must be at most 100 characters.")
        else:
            allowed = {r.name for r in model.query.all()}
            if not set(values) <= allowed:
                raise ValueError("Choose existing function tags and uses.")
        fields[key] = sorted(set(values))
    return fields


def apply_details(plant, fields):
    for key, value in fields.items():
        if key in RELATIONS:
            model = RELATIONS[key]
            records = []
            with db.session.no_autoflush:
                for name in value:
                    record = model.query.filter(db.func.lower(model.name) == name.lower()).first()
                    if record is None:
                        record = model(name=name)
                        db.session.add(record)
                    records.append(record)
            setattr(plant, key, records)
        else:
            setattr(plant, key, value)

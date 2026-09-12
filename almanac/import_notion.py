"""Repeatable, non-overwriting import of the committed Notion snapshot."""

import json
import re
from pathlib import Path
from catalogue import ROTATION_GROUPS, FUNCTIONS, USES
from extensions import db
from garden_data import garden_wording
from models import PlantReference, RotationGroup, PlantFunctionTag, PlantUse


def seed_lookups():
    for name, weight, exempt in ROTATION_GROUPS:
        if not RotationGroup.query.filter_by(name=name).first():
            db.session.add(
                RotationGroup(name=name, feeder_weight=weight, is_rotation_exempt=exempt)
            )
    for model, names in [(PlantFunctionTag, FUNCTIONS), (PlantUse, USES)]:
        for name in names:
            if not model.query.filter_by(name=name).first():
                db.session.add(model(name=name))
    db.session.commit()


def import_notion():
    seed_lookups()
    snapshot = json.loads((Path(__file__).parent / "data/notion_plants.json").read_text())
    added = linked = 0
    for row in snapshot["plants"]:
        slug = re.sub(r"[^a-z0-9]+", "-", row["Name"].lower()).strip("-")
        plant = PlantReference.query.filter_by(notion_url=row["url"]).first()
        if plant:
            continue  # Re-running never overwrites subsequent user edits.
        plant = PlantReference.query.filter_by(slug=slug).first()
        if plant is None:
            plant = PlantReference(
                slug=slug,
                common_name=row["Name"],
                scientific_name=row["Scientific Name"] or "",
                family="",
                summary=garden_wording(row["Description"]) or "",
            )
            db.session.add(plant)
            added += 1
        else:
            linked += 1
        plant.notion_url = row["url"]
        values = {
            "source_url": row["Source URL"],
            "in_row_spacing_cm": row["Plant Spacing cm"],
            "row_spacing_cm": row["Row Spacing cm"],
            "care_notes": row["Care"],
            "management_notes": row["Companion"],
            "uses_notes": "\n".join(v for v in [row["Garden Uses"], row["Cooking"]] if v) or None,
            "sowing_notes": row["Temperate Sow Months"],
        }
        for key, value in values.items():
            if getattr(plant, key) is None:
                setattr(plant, key, garden_wording(value))
        # Explicit mapping from the requested crop list; never infer unknown groups.
        crop = row["Name"].lower()
        group = next(
            (
                group
                for prefix, group in [
                    ("basil", "Anywhere"),
                    ("lettuce", "Anywhere"),
                    ("radish", "Anywhere"),
                    ("carrot", "Roots"),
                    ("broccoli", "Brassicas"),
                    ("bunching onion", "Alliums"),
                    ("eggplant", "Solanums"),
                    ("tomato", "Solanums"),
                    ("pea -", "Legumes"),
                ]
                if crop.startswith(prefix)
            ),
            None,
        )
        if group and plant.rotation_group_id is None:
            plant.rotation_group = RotationGroup.query.filter_by(name=group).one()
    db.session.commit()
    return added, linked


def seed_estimates():
    """Fill gaps only; never silently replace source facts or later user edits."""
    from planning import apply_details

    estimates = json.loads((Path(__file__).parent / "data/ai_estimates.json").read_text())
    count = 0
    for name, values in estimates["plants"].items():
        plant = PlantReference.query.filter_by(common_name=name).first()
        if plant is None or plant.estimated_fields is not None:
            continue
        inferred = []
        for key, value in values.items():
            if key == "rotation_group":
                if plant.rotation_group is None:
                    plant.rotation_group = RotationGroup.query.filter_by(name=value).one()
                    inferred.append(key)
            elif not getattr(plant, key):
                apply_details(plant, {key: garden_wording(value)})
                inferred.append(key)
        plant.estimated_fields = inferred
        count += 1
    db.session.commit()
    return count

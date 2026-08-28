from extensions import db
from models import PlantingMonth, PlantReference


PLANT_REFERENCES = [
    {
        "plant": {
            "slug": "tomato",
            "common_name": "Tomato",
            "scientific_name": "Solanum lycopersicum",
            "family": "Solanaceae",
            "summary": "A productive warm-season crop for garden beds and containers.",
        },
        "planting_months": [1, 9, 10, 11, 12],
    },
    {
        "plant": {
            "slug": "basil",
            "common_name": "Basil",
            "scientific_name": "Ocimum basilicum",
            "family": "Lamiaceae",
            "summary": "A tender aromatic herb suited to warm-season growing.",
        },
        "planting_months": [1, 2, 9, 10, 11, 12],
    },
    {
        "plant": {
            "slug": "lettuce",
            "common_name": "Lettuce",
            "scientific_name": "Lactuca sativa",
            "family": "Asteraceae",
            "summary": "A quick leafy crop with varieties for each season.",
        },
        "planting_months": list(range(1, 13)),
    },
    {
        "plant": {
            "slug": "carrot",
            "common_name": "Carrot",
            "scientific_name": "Daucus carota subsp. sativus",
            "family": "Apiaceae",
            "summary": "A root crop commonly direct-sown through much of the year.",
        },
        "planting_months": [1, 2, 3, 4, 8, 9, 10, 11, 12],
    },
    {
        "plant": {
            "slug": "strawberry",
            "common_name": "Strawberry",
            "scientific_name": "Fragaria × ananassa",
            "family": "Rosaceae",
            "summary": "A compact perennial fruit for pots, baskets, and beds.",
        },
        "planting_months": [6, 7],
    },
    {
        "plant": {
            "slug": "zucchini",
            "common_name": "Zucchini",
            "scientific_name": "Cucurbita pepo",
            "family": "Cucurbitaceae",
            "summary": "A vigorous warm-season crop that produces generously.",
        },
        "planting_months": [1, 8, 9, 10, 11, 12],
    },
]


def _update_fields(record, values: dict) -> None:
    for field, value in values.items():
        setattr(record, field, value)


def seed_reference_data() -> None:
    for data in PLANT_REFERENCES:
        plant_data = data["plant"]
        plant = PlantReference.query.filter_by(slug=plant_data["slug"]).first()
        if plant is None:
            plant = PlantReference()
            db.session.add(plant)
        _update_fields(plant, plant_data)

        target_months = set(data["planting_months"])
        existing_months = {
            month.month_number: month for month in plant.planting_months
        }
        for month_number, month in existing_months.items():
            if month_number not in target_months:
                plant.planting_months.remove(month)
        for month_number in target_months - existing_months.keys():
            plant.planting_months.append(
                PlantingMonth(month_number=month_number)
            )

    db.session.commit()

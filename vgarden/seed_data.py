"""Demo seed data for the Virtual Garden.

Runs on startup only when the `gardens` table is empty (a fresh database, e.g.
after `docker compose down -v`). It creates:

  * 12 gardens owned by user id 1 (the demo Auth account — see auth/seed_data.py),
    so every garden the demo user opens already has content;
  * garden 1 ("Backyard Beds") fully populated — 12 areas, 12 containers, and
    15 plantings, each with a location — so the areas / containers / plantings /
    planting_locations tables each hold >= 10 rows for the showcase.

Garden ids are assigned 1..12 from a fresh SQLite database, matching the
ownership rows auth seeds for the same demo user.
"""

from datetime import date, timedelta

from extensions import db
from models import Container, Garden, GardenArea, Planting, PlantingLocation

DEMO_OWNER_ID = 1

GARDENS = [
    ("Backyard Beds", "The main raised-bed vegetable garden.", "Melbourne, Victoria, Australia", -37.8136, 144.9631, "temperate"),
    ("Front Verandah Pots", "Container herbs and salad by the front door.", "Melbourne, Victoria, Australia", -37.8140, 144.9633, "temperate"),
    ("Community Plot 14", "A shared allotment bed at the local garden.", "Brunswick, Victoria, Australia", -37.7670, 144.9600, "temperate"),
    ("Balcony Garden", "Apartment balcony, morning sun only.", "Sydney, New South Wales, Australia", -33.8688, 151.2093, "warm temperate"),
    ("Nan's Cottage Garden", "Old country garden, mixed ornamental and edible.", "Ballarat, Victoria, Australia", -37.5622, 143.8503, "cool temperate"),
    ("Rooftop Boxes", "Wicking boxes on a north-facing rooftop.", "Brisbane, Queensland, Australia", -27.4698, 153.0251, "subtropical"),
    ("Side Passage Greens", "Narrow shady strip, leafy crops.", "Melbourne, Victoria, Australia", -37.8150, 144.9640, "temperate"),
    ("The Orchard Corner", "Three dwarf fruit trees and understorey.", "Adelaide, South Australia, Australia", -34.9285, 138.6007, "mediterranean"),
    ("School Garden Bed", "Volunteer bed at the primary school.", "Geelong, Victoria, Australia", -38.1499, 144.3617, "temperate"),
    ("Winter Glasshouse", "Small polycarbonate house for winter crops.", "Hobart, Tasmania, Australia", -42.8821, 147.3272, "cool temperate"),
    ("Herb Spiral", "A stone herb spiral by the kitchen.", "Perth, Western Australia, Australia", -31.9523, 115.8613, "mediterranean"),
    ("New Plot (planning)", "Bare ground, still being planned out.", "", None, None, ""),
]

AREAS = [
    ("North Bed", "bed"), ("South Bed", "bed"), ("East Bed", "bed"), ("West Bed", "bed"),
    ("Herb Bed", "bed"), ("Salad Row", "row"), ("Climbing Frame Row", "row"),
    ("Pumpkin Patch", "plot"), ("Strawberry Bed", "bed"), ("Nursery Bed", "bed"),
    ("Compost Corner", "other"), ("Glasshouse Bench", "greenhouse"),
]

CONTAINERS = [
    ("Terracotta Pot 1", "pot"), ("Terracotta Pot 2", "pot"), ("Half Wine Barrel", "box"),
    ("Wicking Box A", "box"), ("Wicking Box B", "box"), ("Hanging Basket", "hanging-basket"),
    ("Grow Bag 1", "other"), ("Grow Bag 2", "other"), ("Trough Planter", "box"),
    ("Styrofoam Box", "box"), ("Ceramic Bowl", "pot"), ("Self-watering Pot", "pot"),
]

PLANTINGS = [
    ("Tomato (Roma)", 4, "growing", "fruiting"),
    ("Tomato (Cherry)", 2, "growing", "flowering"),
    ("Basil (Genovese)", 6, "growing", "vegetative"),
    ("Lettuce (Cos)", 8, "growing", "heading"),
    ("Lettuce (Oak Leaf)", 8, "harvested", None),
    ("Carrot (Nantes)", 30, "sown", None),
    ("Zucchini (Black Beauty)", 2, "growing", "flowering"),
    ("Strawberry (Alpine)", 10, "growing", "fruiting"),
    ("Capsicum (Red)", 3, "growing", "vegetative"),
    ("Spring Onion", 20, "growing", "vegetative"),
    ("Snow Pea", 12, "growing", "climbing"),
    ("Bush Bean (Purple King)", 15, "planned", None),
    ("Beetroot (Bull's Blood)", 18, "sown", None),
    ("Kale (Cavolo Nero)", 5, "growing", "vegetative"),
    ("Coriander", 12, "growing", "bolting"),
]


def seed_demo_data() -> None:
    if Garden.query.first() is not None:
        return

    gardens = []
    for name, desc, label, lat, lon, zone in GARDENS:
        garden = Garden(
            owner_id=DEMO_OWNER_ID,
            name=name,
            description=desc,
            location_label=label,
            latitude=lat,
            longitude=lon,
            climate_zone=zone,
        )
        db.session.add(garden)
        gardens.append(garden)
    db.session.flush()

    main = gardens[0]

    areas = []
    for i, (name, area_type) in enumerate(AREAS):
        area = GardenArea(
            garden_id=main.id,
            name=name,
            area_type=area_type,
            pos_x=float(i % 4) * 2.5,
            pos_y=float(i // 4) * 2.5,
            width=2.0,
            length=1.2,
        )
        db.session.add(area)
        areas.append(area)
    db.session.flush()

    containers = []
    for i, (name, container_type) in enumerate(CONTAINERS):
        container = Container(
            garden_area_id=areas[i % len(areas)].id,
            name=name,
            container_type=container_type,
            pos_x=float(i) * 0.6,
            pos_y=0.3,
            volume_liters=float(15 + (i % 5) * 10),
        )
        db.session.add(container)
        containers.append(container)
    db.session.flush()

    today = date.today()
    for i, (crop, qty, state, stage) in enumerate(PLANTINGS):
        planting = Planting(
            garden_id=main.id,
            crop_name=crop,
            quantity=qty,
            lifecycle_state=state,
            growth_stage=stage,
            planted_date=today - timedelta(days=20 + i * 3) if state != "planned" else None,
            expected_harvest_date=today + timedelta(days=25 + i * 4),
        )
        db.session.add(planting)
        db.session.flush()

        # Alternate plantings between an area and a container so both tables fill.
        if i % 2 == 0:
            location = PlantingLocation(
                planting_id=planting.id, garden_area_id=areas[i % len(areas)].id
            )
        else:
            location = PlantingLocation(
                planting_id=planting.id, container_id=containers[i % len(containers)].id
            )
        db.session.add(location)

    db.session.commit()

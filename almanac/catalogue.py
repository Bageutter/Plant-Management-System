"""Controlled vocabulary shared by forms, API and seed data."""

CHOICES = {
    "feeder_type": ["heavy feeder", "light feeder", "nitrogen fixer"],
    "water_needs": ["low", "moderate", "high"],
    "sun_needs": ["full sun", "part shade", "shade"],
    "forest_layer": [
        "canopy",
        "sub-canopy",
        "shrub",
        "herbaceous",
        "rhizosphere",
        "groundcover",
        "vine",
    ],
    "part_used": ["leaf", "root", "fruit", "flower", "bark", "seed"],
}
FUNCTIONS = [
    "nitrogen fixer",
    "dynamic accumulator",
    "pollinator attractor",
    "pest confuser/repellent",
    "mulch/chop-and-drop plant",
    "windbreak",
]
USES = ["culinary", "medicinal", "fodder", "dye", "fibre", "ornamental", "timber"]
# Planning defaults, not measured nutrient requirements for every species.
ROTATION_GROUPS = [
    ("Alliums", "medium", False),
    ("Brassicas", "heavy", False),
    ("Cucurbits", "heavy", False),
    ("Legumes", "light", False),
    ("Roots", "light", False),
    ("Solanums", "heavy", False),
    ("Anywhere", "light", True),
    ("Perennials", "medium", True),
]
NUMERIC = {
    "yield_qty": "Yield per plant",
    "in_row_spacing_cm": "In-row spacing (cm)",
    "row_spacing_cm": "Between-row spacing (cm)",
    "succession_interval_days": "Succession interval (days)",
    "harvest_window_weeks": "Harvest window (weeks)",
    "soil_ph_min": "Minimum soil pH",
    "soil_ph_max": "Maximum soil pH",
}
TEXT = {
    "yield_wording": "Yield notes",
    "yield_unit": "Yield unit (e.g. kg, fruit)",
    "management_notes": "Organic / companion management notes",
    "care_notes": "Care notes",
    "uses_notes": "Uses and cooking notes",
    "sowing_notes": "Sowing timing notes",
}

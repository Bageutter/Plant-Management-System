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

FIELD_HELP = {
    "yield_wording": "How the crop is harvested: all at once, or in several pickings. Use this with the quantity and harvest window below.",
    "yield_qty": "The total harvest from one established plant over its harvest window. For example, 8 fruit or 1.5 kg. Actual harvests vary with growing conditions.",
    "yield_unit": "What the recorded harvest quantity counts or weighs, such as kg, heads, roots or fruit.",
    "in_row_spacing_cm": "Distance from the centre of one plant to the next along a row, measured in centimetres.",
    "row_spacing_cm": "Distance between the centres of neighbouring rows, in centimetres. Allow additional room for paths and access.",
    "succession_interval_days": "How many days to wait before sowing another small batch, so harvests arrive at different times within the growing season.",
    "harvest_window_weeks": "How long a planting can be picked from once harvest begins. A one-week root or head crop is picked once; a longer window can include repeated pickings. This is not time from sowing to maturity.",
    "feeder_type": "Heavy feeders need more nutrients. Light feeders need less. Nitrogen fixers work with root bacteria to capture nitrogen; this does not mean they immediately feed nearby plants.",
    "soil_ph_min": "The lower end of the preferred soil acidity range. pH 7 is neutral; below 7 is acidic and above 7 is alkaline. A soil test tells you your bed's pH.",
    "soil_ph_max": "The upper end of the preferred soil acidity range. Read it together with minimum pH; the two numbers describe a range, not a fertiliser dose.",
    "water_needs": "Low: tolerate drier soil once established. Moderate: water when the soil starts to dry. High: keep moisture more consistent. Weather, soil and containers change how often to water.",
    "sun_needs": "Full sun is usually 6 or more hours of direct sun a day. Part shade is roughly 3–6 hours. Shade means mostly indirect light; afternoon shelter can help in hot climates.",
    "forest_layer": "Where the plant sits in a layered garden: canopy (tall trees), sub-canopy (smaller trees), shrub, herbaceous (soft-stemmed plants), rhizosphere (root crops), groundcover or vine.",
    "function_tags": "The jobs a plant can do in a garden, such as attracting pollinators, covering soil or providing mulch. One plant can have several jobs.",
    "uses": "The main purposes for growing the plant, such as food, flowers, fibre or timber. A use category alone does not tell you how to prepare it safely.",
    "part_used": "Which part is normally harvested or used. Other parts of the same plant may not be suitable for the same purpose.",
    "rotation_group": "A group to move between beds from season to season. Avoid repeatedly growing the same group in the same soil, to help interrupt crop-specific pests and diseases.",
    "feeder_weight": "The group's general nutrient demand: light, medium or heavy. Use it alongside soil condition and the crop's own feeding needs when planning what to grow next.",
    "guild_links": "Plants that can share a garden area while doing different jobs. Choose a companion for its stated role, and leave enough space and light for both plants.",
    "pests": "Animals or insects that commonly damage this plant. Identify what is present before choosing a treatment.",
    "diseases": "Plant illnesses to watch for. Similar symptoms can have different causes, so check the plant and growing conditions before treating.",
}

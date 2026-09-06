"""Garden-facing wording and opt-in starter companion links."""

from extensions import db
from models import Disease, Pest, PlantReference, PlantCompanion, PlantFunctionTag

# Exact wording replacements avoid rewriting a gardener's own descriptions.
COPY_REPLACEMENTS = {
    "Sweet basil paired with tomato in the demo relationship data.": "Sweet basil with aromatic leaves for the kitchen and flowers for visiting insects.",
    "Culinary herb and herbaceous layer in the synthetic Tomato Edge Guild.": "Culinary herb for the herbaceous layer; allow a few stems to flower for visiting insects.",
    "Cylindrical carrot used for container and timing examples.": "Cylindrical carrot suited to loose, well-prepared soil or a deep container.",
    "Container-suitable root crop in the Release 0 catalogue.": "Root crop suited to a deep container with loose soil.",
    "Compact butterhead lettuce for the Release 0 catalogue.": "Compact butterhead lettuce with tender leaves for fresh picking.",
    "Compact flowering edge plant for the synthetic Tomato Edge Guild.": "Compact flowering plant for sunny bed edges and borders.",
    "Flowering edge plant and pollinator-support role in the synthetic Tomato Edge Guild.": "Flowering edge plant for a varied insect-friendly border.",
    "Shelling pea used as a cool-season catalogue example.": "Cool-season shelling pea; pick pods while the peas are young and tender.",
    "Fast crop included to demonstrate succession relationships.": "Quick-growing radish suited to small, repeated sowings.",
    "Dark slicing tomato included as synthetic planning data.": "Dark slicing tomato for warm-season growing with a sturdy stake or cage.",
    "Canopy and anchor crop in the synthetic Tomato Edge Guild.": "Tall summer crop; keep lower-growing companions outside its main root and shade area.",
}

PROBLEM_DESCRIPTIONS = {
    "Aphids": "Small sap-feeding insects that often gather on soft new growth and beneath leaves. Identification and organic management guidance will be expanded here.",
    "Slugs and snails": "Soft-bodied garden pests that chew seedlings and leaves, often feeding overnight or after rain. Identification and organic management guidance will be expanded here.",
    "Powdery mildew": "A group of fungal diseases that can produce pale, powder-like patches on leaves and stems. Crop-specific prevention and management guidance will be expanded here.",
}

APHID_HOST_PREFIXES = (
    "broccoli",
    "bunching-onion",
    "eggplant",
    "lettuce",
    "pea-",
    "sunflower",
    "sweet-corn",
    "tomato",
    "zinnia",
)
SLUG_HOST_PREFIXES = (
    "alyssum",
    "basil",
    "bergamot",
    "broccoli",
    "lettuce",
    "marigold",
    "pea-",
    "radish",
    "sunflower",
    "zinnia",
)


def suggested_pests(slug):
    """Conservative starter links for the AI-assisted catalogue seed."""
    pests = []
    if slug.startswith(APHID_HOST_PREFIXES):
        pests.append("Aphids")
    if slug.startswith(SLUG_HOST_PREFIXES):
        pests.append("Slugs and snails")
    return pests


def garden_wording(value):
    if not isinstance(value, str):
        return value
    for old, new in COPY_REPLACEMENTS.items():
        value = value.replace(old, new)
    for prefix in ("AI estimate: ", "AI suggestion: ", "AI identity assumption: "):
        if value.startswith(prefix):
            value = value[len(prefix) :]
            value = value[0].upper() + value[1:]
    return value.replace(
        "Single destructive harvest; one plant is harvested once.",
        "Harvest each plant once during this picking period.",
    )


def refresh_garden_wording():
    changed = 0
    for plant in PlantReference.query.all():
        for key in ("summary", "yield_wording", "management_notes", "uses_notes"):
            value = getattr(plant, key)
            cleaned = garden_wording(value)
            if cleaned != value:
                setattr(plant, key, cleaned)
                changed += 1
    for model in (Pest, Disease):
        for record in model.query.all():
            description = PROBLEM_DESCRIPTIONS.get(record.name)
            if description and not record.description:
                record.description = description
                changed += 1
    db.session.commit()
    return changed


# General habitat suggestions, not claims of guaranteed crop-specific pest control.
# References: https://www.rhs.org.uk/advice/grow-your-own/features/companion-planting
# https://extension.umn.edu/garden-and-home/yard-and-garden/gardening-in-minnesota/companion-planting-in-home-gardens
COMPANIONS = {
    "alyssum": "A low flowering edge provides nectar for visiting insects. Keep it outside the crop's spacing so it does not crowd young plants.",
    "marigold-french-marigold": "Add a sunny flowering border for insect habitat. Leave enough space between the flowers and the crop for light and airflow.",
    "hyssop": "Use this flowering herb along a sunny border for bees. Keep its permanent woody base outside the vegetable bed so it will not compete with small crops.",
    "bergamot-lemon-mint": "Add flowers for bees in a sunny border. Allow airflow and keep the taller stems from shading shorter plants.",
    "zinnia": "Plant on a sunny outer edge for flowers that visiting insects can use. Choose a position that will not shade the crop.",
    "basil-genovese": "Grow on the sunny side with room for both plants. Let a few basil stems flower to provide nectar for visiting insects.",
}


def seed_guilds():
    """Add starter suggestions to catalogue plants, retaining existing links/notes."""
    function = PlantFunctionTag.query.filter_by(name="pollinator attractor").one()
    plants = {p.slug: p for p in PlantReference.query.all()}
    added = 0
    for slug, plant in plants.items():
        if slug.startswith(("tomato", "eggplant", "cucumber", "sweet-corn", "sweet-potato")):
            companions = ("basil-genovese", "marigold-french-marigold")
        elif slug.startswith(
            ("lettuce", "carrot", "radish", "broccoli", "bunching-onion", "pea-", "basil")
        ):
            companions = ("alyssum", "marigold-french-marigold")
        elif slug.startswith(("japanese-raisin", "stepover", "horseradish")):
            companions = ("hyssop", "alyssum")
        elif slug.startswith(("alyssum", "hyssop", "bergamot", "marigold", "zinnia", "sunflower")):
            companions = ("bergamot-lemon-mint", "zinnia", "alyssum")
        else:
            continue  # Do not guess growing companions for unidentified/unusual plants.
        for companion_slug in companions:
            companion = plants.get(companion_slug)
            if companion is None or companion.id == plant.id:
                continue
            identity = (plant.id, companion.id, function.id)
            if db.session.get(PlantCompanion, identity):
                continue
            db.session.add(
                PlantCompanion(
                    plant_id=plant.id,
                    companion_id=companion.id,
                    function_id=function.id,
                    notes=COMPANIONS[companion_slug],
                )
            )
            added += 1
    db.session.commit()
    return added

"""Curated, source-backed guidance for pest and disease reference pages."""


PEST_GUIDES = {
    "Aphids": {
        "eyebrow": "Sap-feeding pest",
        "status": "Usually manageable",
        "intro": (
            "Aphids cluster on tender shoots and leaf undersides. A few are usually "
            "tolerable; act when colonies are growing, leaves are curling, or seedlings "
            "are losing vigour."
        ),
        "signs": [
            "Clusters of tiny green, black, yellow or pink insects",
            "Sticky honeydew on leaves, sometimes followed by black sooty mould",
            "Curled or distorted new growth and white shed skins",
            "Ants repeatedly travelling up stems to feed on honeydew",
        ],
        "control_steps": [
            {
                "number": "01",
                "label": "Start gently",
                "title": "Rinse them off",
                "body": (
                    "Support the stem and use a firm stream of water, especially beneath "
                    "the leaves. Check again in two or three days."
                ),
            },
            {
                "number": "02",
                "label": "Build resilience",
                "title": "Make room for predators",
                "body": (
                    "Avoid broad-spectrum insecticides. Ladybirds, hoverfly larvae, "
                    "lacewings and tiny parasitic wasps naturally feed on aphids."
                ),
            },
            {
                "number": "03",
                "label": "If damage continues",
                "title": "Use a contact spray",
                "body": (
                    "Choose a commercially formulated insecticidal soap or horticultural "
                    "oil labelled for the plant. Test a small area, follow the label and "
                    "coat the aphids directly, including leaf undersides."
                ),
            },
        ],
        "companions": [
            {
                "name": "Sweet Alyssum",
                "slug": "alyssum",
                "badge": "Beneficial-insect habitat",
                "body": (
                    "Its small flowers provide nectar and pollen for hoverflies and other "
                    "aphid predators. Keep it at the bed edge so it does not crowd crops."
                ),
            },
            {
                "name": "Nasturtium",
                "external_url": (
                    "https://www.rhs.org.uk/plants/nasturtiums/annual-nasturtiums/"
                    "how-to-grow-annual-nasturtiums"
                ),
                "badge": "Trap-crop experiment",
                "body": (
                    "Nasturtiums can host aphids, especially blackfly. Grow one nearby as "
                    "a sacrificial plant only if you will inspect it and pinch out heavily "
                    "infested shoots before the colony spreads."
                ),
            },
        ],
        "support_eyebrow": "Garden allies",
        "support_title": "Plants that may help the system",
        "spray_note": (
            "Contact sprays only affect insects they touch. Avoid spraying drought-stressed "
            "plants or during hot weather, and never spray flowers while bees are visiting."
        ),
        "sources": [
            {
                "label": "UC IPM — Aphids",
                "url": "https://ipm.ucanr.edu/home-and-landscape/aphids/",
            },
            {
                "label": "RHS — Companion planting",
                "url": "https://www.rhs.org.uk/advice/grow-your-own/features/companion-planting",
            },
            {
                "label": "RHS — Growing nasturtiums",
                "url": (
                    "https://www.rhs.org.uk/plants/nasturtiums/annual-nasturtiums/"
                    "how-to-grow-annual-nasturtiums"
                ),
            },
        ],
    }
}


DISEASE_GUIDES = {
    "Powdery mildew": {
        "eyebrow": "Fungal disease group",
        "status": "Act early",
        "intro": (
            "Powdery mildew forms pale, flour-like patches across leaves and stems. "
            "It usually weakens rather than immediately kills a plant, but early changes "
            "to airflow, spacing and care can stop it becoming severe."
        ),
        "signs": [
            "White or grey powdery patches, often starting on upper leaf surfaces",
            "Young leaves that curl, yellow or become distorted",
            "A gradual loss of vigour, especially on crowded or shaded growth",
            "Dry-looking surface growth even when there has been little rain",
        ],
        "control_steps": [
            {
                "number": "01",
                "label": "Confirm the pattern",
                "title": "Check both sides of the leaf",
                "body": (
                    "Look for surface powder rather than a wipeable splash or residue. "
                    "Different powdery mildew fungi affect different host plants, so use "
                    "the affected plant to narrow the diagnosis."
                ),
            },
            {
                "number": "02",
                "label": "Change the conditions",
                "title": "Open up the plant",
                "body": (
                    "Improve airflow, avoid dense planting and excessive nitrogen, and "
                    "keep roots evenly watered. Use a sunny position where that plant "
                    "normally prefers sun."
                ),
            },
            {
                "number": "03",
                "label": "Reduce the source",
                "title": "Remove the worst growth",
                "body": (
                    "Prune a small outbreak promptly and dispose of heavily affected "
                    "material. Clean tools before moving to another plant."
                ),
            },
            {
                "number": "04",
                "label": "If it keeps spreading",
                "title": "Choose a labelled treatment",
                "body": (
                    "For a mild or moderate infection, a horticultural or plant-based oil "
                    "labelled for powdery mildew may help. Sulfur products are mainly "
                    "preventive and must be used before or very early in infection."
                ),
            },
        ],
        "companions": [
            {
                "name": "Give plants breathing room",
                "badge": "Prevention",
                "body": (
                    "Space and prune plants for moving air. This reduces the still, humid "
                    "microclimate in which powdery mildew commonly builds up."
                ),
            },
            {
                "name": "Choose resistant varieties",
                "badge": "Next season",
                "body": (
                    "When mildew returns every year, choose a resistant or less-susceptible "
                    "variety and clear affected plant debris at the end of the season."
                ),
            },
        ],
        "support_eyebrow": "Prevention",
        "support_title": "Make the garden less inviting",
        "spray_note": (
            "Never apply horticultural oil within two weeks of sulfur, during hot weather, "
            "or to a drought-stressed plant. Some crops are sensitive, so follow the label "
            "and test a small area first."
        ),
        "sources": [
            {
                "label": "UC IPM — Powdery mildew",
                "url": (
                    "https://ipm.ucanr.edu/home-and-landscape/"
                    "powdery-mildew-on-vegetables/"
                ),
            },
            {
                "label": "RHS — Powdery mildews",
                "url": "https://www.rhs.org.uk/disease/powdery-mildews",
            },
        ],
    }
}

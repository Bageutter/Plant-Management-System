from datetime import datetime, timezone

from extensions import db
from models import AIChatMessage, AILoopRun, PlantingMonth, PlantReference

# Demo user id 1 (auth's demo@plant.test). A short seeded conversation so the
# chat + loop-run tables are populated for the showcase.
DEMO_OWNER_KEY = "user:1"
DEMO_CHAT = [
    ("When should I plant tomatoes?", "Tomatoes are listed for January and September to December."),
    ("What can I plant in April?", "Carrot, spinach, pea, kale, coriander and beetroot are listed for April."),
    ("Tell me about basil.", "Basil (Ocimum basilicum, Lamiaceae) is a tender warm-season herb; listed for Jan, Feb and Sep to Dec."),
    ("Which herbs are perennial?", "Rosemary and mint are the perennial herbs in the almanac; basil and coriander are annuals."),
    ("Compare lettuce and spinach.", "Both are cool-season leaf crops; lettuce is listed year-round, spinach only March to August."),
    ("What's in the Cucurbitaceae family?", "Zucchini and cucumber are the two Cucurbitaceae entries."),
    ("When do I sow peas?", "Peas are listed for March, April, May, August and September."),
    ("Is strawberry an annual?", "No — strawberry is a compact perennial; it's listed for planting in June and July."),
    ("What can I grow in winter here?", "Spinach, kale, peas and coriander cover the cooler months in the almanac."),
    ("Give me a fast crop.", "Lettuce is the quickest — leafy, listed every month, cut-and-come-again."),
]


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
    {
        "plant": {
            "slug": "capsicum",
            "common_name": "Capsicum",
            "scientific_name": "Capsicum annuum",
            "family": "Solanaceae",
            "summary": "A warm-season fruiting vegetable that needs a long, frost-free season.",
        },
        "planting_months": [9, 10, 11],
    },
    {
        "plant": {
            "slug": "spinach",
            "common_name": "Spinach",
            "scientific_name": "Spinacia oleracea",
            "family": "Amaranthaceae",
            "summary": "A fast cool-season leaf crop that bolts in summer heat.",
        },
        "planting_months": [3, 4, 5, 6, 7, 8],
    },
    {
        "plant": {
            "slug": "pea",
            "common_name": "Pea",
            "scientific_name": "Pisum sativum",
            "family": "Fabaceae",
            "summary": "A cool-season climbing legume; sow direct and give it support.",
        },
        "planting_months": [3, 4, 5, 8, 9],
    },
    {
        "plant": {
            "slug": "bean",
            "common_name": "Bush Bean",
            "scientific_name": "Phaseolus vulgaris",
            "family": "Fabaceae",
            "summary": "A quick warm-season legume; direct-sow after the last frost.",
        },
        "planting_months": [9, 10, 11, 12, 1, 2],
    },
    {
        "plant": {
            "slug": "cucumber",
            "common_name": "Cucumber",
            "scientific_name": "Cucumis sativus",
            "family": "Cucurbitaceae",
            "summary": "A vining warm-season crop that fruits fast in fertile, moist soil.",
        },
        "planting_months": [9, 10, 11, 12, 1],
    },
    {
        "plant": {
            "slug": "beetroot",
            "common_name": "Beetroot",
            "scientific_name": "Beta vulgaris",
            "family": "Amaranthaceae",
            "summary": "A dual-purpose root and leaf crop, direct-sown across most of the year.",
        },
        "planting_months": [1, 2, 3, 8, 9, 10, 11, 12],
    },
    {
        "plant": {
            "slug": "kale",
            "common_name": "Kale",
            "scientific_name": "Brassica oleracea",
            "family": "Brassicaceae",
            "summary": "A hardy leafy brassica that sweetens after cold weather.",
        },
        "planting_months": [2, 3, 4, 5, 9, 10],
    },
    {
        "plant": {
            "slug": "coriander",
            "common_name": "Coriander",
            "scientific_name": "Coriandrum sativum",
            "family": "Apiaceae",
            "summary": "A fast herb grown for leaf and seed; bolts quickly in heat.",
        },
        "planting_months": [3, 4, 5, 9, 10],
    },
    {
        "plant": {
            "slug": "mint",
            "common_name": "Mint",
            "scientific_name": "Mentha spicata",
            "family": "Lamiaceae",
            "summary": "A spreading perennial herb best confined to a pot.",
        },
        "planting_months": [9, 10, 11, 3, 4],
    },
    {
        "plant": {
            "slug": "rosemary",
            "common_name": "Rosemary",
            "scientific_name": "Salvia rosmarinus",
            "family": "Lamiaceae",
            "summary": "A drought-tolerant woody perennial herb for a sunny, well-drained spot.",
        },
        "planting_months": [3, 4, 9, 10],
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


def _fake_trace(question: str, answer: str, run_id: str) -> list[dict]:
    ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    common = {"run_id": run_id, "service": "almanac"}
    return [
        {"ts": ts, "phase": "plan", "elapsed_ms": 0, "question": question, **common},
        {"ts": ts, "phase": "act", "elapsed_ms": 800, "iteration": 1,
         "carried_feedback": "(none)", "draft": answer, "draft_chars": len(answer), **common},
        {"ts": ts, "phase": "observe", "elapsed_ms": 1200, "iteration": 1,
         "verdict": "approved", "issues": "(none)", **common},
        {"ts": ts, "phase": "adapt", "elapsed_ms": 1200, "iteration": 1, "decision": "accept", **common},
    ]


def seed_demo_chat() -> None:
    if AIChatMessage.query.filter_by(owner_key=DEMO_OWNER_KEY).first() is not None:
        return
    for i, (question, answer) in enumerate(DEMO_CHAT):
        user = AIChatMessage(owner_key=DEMO_OWNER_KEY, role="user", content=question)
        assistant = AIChatMessage(
            owner_key=DEMO_OWNER_KEY, role="assistant", content=answer, source_slugs=[]
        )
        db.session.add_all([user, assistant])
        db.session.flush()
        run_id = f"almanac-seed-{i + 1:02d}"
        db.session.add(
            AILoopRun(
                owner_key=DEMO_OWNER_KEY,
                message_id=assistant.id,
                run_id=run_id,
                question=question,
                final_answer=answer,
                iterations=1,
                verdict="approved",
                transcript_path=f"tools/ai-loop/logs/reports/almanac/{run_id}.md",
                trace=_fake_trace(question, answer, run_id),
            )
        )
    db.session.commit()

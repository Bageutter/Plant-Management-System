"""Demo seed data for Plant Health Monitoring.

Runs on startup only when the `assessments` table is empty (a fresh database).
It inserts 12 example assessments — text-only, no photos — so the showcase opens
with a populated history and the assessments table holds >= 10 rows.

These are illustrative records, not real model output.
"""

from datetime import datetime, timezone

from ai import describe_score
from extensions import db
from models import Assessment, AssessmentAILoopRun, AssessmentChatMessage

# A short seeded conversation on the first assessment so the chat + loop-run
# tables are populated for the showcase.
DEMO_CHAT = [
    ("Why do you think it's overwatering and not a nutrient problem?",
     "The yellowing is described as bottom-up and progressive, which fits overwatering; nothing in the notes points to a nutrient deficiency, so that stays a maybe."),
    ("How often should I water instead?",
     "The recommendation is twice a week — let the top 3 cm of soil dry between waterings."),
    ("The upper leaves look fine — is that a good sign?",
     "Yes. Healthy upper growth with only lower-leaf symptoms usually means the problem is recent and recoverable."),
    ("Should I add fertiliser now?",
     "Only after easing off the water for a week or two — feeding a waterlogged root zone won't help and can make it worse."),
    ("What would help you be more sure?",
     "A close-up photo of an affected leaf and the soil type / drainage, per the 'missing information' note."),
    ("Can I still eat the fruit?",
     "The assessment doesn't cover fruit safety — that's outside what was submitted. The plant issue described is cultural, not a contamination risk."),
    ("How long until I see improvement?",
     "With watering corrected, expect the plant to stop declining within a week; existing yellow leaves won't turn green again."),
    ("Is it too late to save it?",
     "No — the status is 'at risk', not 'unhealthy', and upper growth is fine, so acting now should turn it around."),
    ("Should I remove the yellow leaves?",
     "You can remove fully yellow lower leaves; they won't recover and removing them reduces stress on the plant."),
    ("Anything else?",
     "Mulch to keep soil moisture even, and check the pot or bed actually drains — standing water is the usual cause."),
]

_SEED = [
    ("Tomato (Roma) — north bed", "Lower leaves yellowing from the bottom up, some curling. Watered every second day.",
     "at_risk", 52, "medium", "Yellowing is bottom-up and progressive, which points to a nutrient or watering issue, but no photo to confirm.",
     "Tomato", "Early nitrogen deficiency or overwatering; upper growth still healthy.",
     [{"name": "Lower-leaf chlorosis", "severity": "medium", "evidence": "yellowing from the bottom up"}],
     [{"action": "Ease off watering to twice a week", "priority": "high", "details": "let the top 3 cm of soil dry between waterings"},
      {"action": "Side-dress with a balanced fertiliser", "priority": "medium", "details": "water in a handful of pelletised manure"}],
     ["A close-up photo of an affected leaf", "Soil type and drainage"]),
    ("Basil in patio pot", "Leaves have small brown spots and the plant looks leggy. Full afternoon sun.",
     "at_risk", 58, "low", "Brown spots have several possible causes and there is no photo.",
     "Basil", "Possible sun scorch or early fungal leaf spot; growth is otherwise vigorous.",
     [{"name": "Leaf spotting", "severity": "medium", "evidence": "small brown spots on leaves"},
      {"name": "Legginess", "severity": "low", "evidence": "plant looks leggy"}],
     [{"action": "Pinch out the growing tips", "priority": "medium", "details": "encourages bushier growth"},
      {"action": "Move to morning sun / afternoon shade", "priority": "medium", "details": "reduces scorch risk"}],
     ["A photo of the spotted leaves", "Whether spots have a yellow halo"]),
    ("Zucchini", "White powdery coating spreading across older leaves over the last week.",
     "unhealthy", 34, "high", "White powdery coating on cucurbit leaves is a textbook, distinctive symptom.",
     "Zucchini", "Powdery mildew, moderately advanced on older foliage.",
     [{"name": "Powdery mildew", "severity": "high", "evidence": "white powdery coating spreading on older leaves"}],
     [{"action": "Remove and bin the worst-affected leaves", "priority": "high", "details": "do not compost them"},
      {"action": "Spray a milk or potassium-bicarbonate solution weekly", "priority": "high", "details": "cover both leaf surfaces, early morning"},
      {"action": "Improve airflow", "priority": "medium", "details": "thin crowded growth"}],
     []),
    ("Lettuce (Cos) — salad row", "Growing well, deep green, no visible problems. Harvested outer leaves twice.",
     "healthy", 90, "high", "A clear description of healthy growth with no reported symptoms.",
     "Lettuce", "Thriving; routine care only.",
     [],
     [{"action": "Keep harvesting outer leaves", "priority": "low", "details": "cut-and-come-again keeps the plant productive"}],
     []),
    ("Strawberry bed", "Some leaves have irregular purple-red blotches. Fruit is small this year.",
     "at_risk", 55, "medium", "Purple-red leaf blotching is consistent with a leaf-spot fungus, but small fruit has many causes.",
     "Strawberry", "Likely leaf spot plus a possible feeding or age issue affecting fruit size.",
     [{"name": "Leaf blotch", "severity": "medium", "evidence": "irregular purple-red blotches on leaves"},
      {"name": "Small fruit", "severity": "low", "evidence": "fruit is small this year"}],
     [{"action": "Remove old and blotched leaves after fruiting", "priority": "medium", "details": "reduces overwintering spores"},
      {"action": "Renew the bed if plants are over three years old", "priority": "low", "details": "productivity drops with age"}],
     ["Plant age", "Feeding schedule"]),
    ("Capsicum (Red)", "Flowers keep dropping before setting fruit. Warm spell recently.",
     "at_risk", 60, "medium", "Flower drop in capsicum during hot weather is common, but nutrient and watering swings do the same.",
     "Capsicum", "Heat-stress flower drop; the plant itself looks healthy.",
     [{"name": "Blossom drop", "severity": "medium", "evidence": "flowers dropping before setting fruit during a warm spell"}],
     [{"action": "Shade the plant during heatwaves", "priority": "medium", "details": "30–50% shade cloth over 32 °C"},
      {"action": "Keep soil moisture even", "priority": "medium", "details": "mulch and water deeply, avoid drying out"}],
     ["Day and night temperatures", "Whether watering has been consistent"]),
    ("Rosemary in terracotta pot", "Some lower stems have gone brown and brittle. Rarely watered.",
     "at_risk", 62, "low", "Brown brittle lower stems could be normal ageing or root problems; no photo and little detail.",
     "Rosemary", "Likely normal woody ageing with possible dry stress at the base.",
     [{"name": "Lower-stem dieback", "severity": "low", "evidence": "lower stems brown and brittle"}],
     [{"action": "Prune out the dead wood", "priority": "low", "details": "cut back to green growth"},
      {"action": "Water more deeply but still infrequently", "priority": "low", "details": "terracotta dries fast in sun"}],
     ["A photo of the base of the plant", "How old the plant is"]),
    ("Kale (Cavolo Nero)", "Small holes appearing in the leaves, and I found green caterpillars underneath.",
     "unhealthy", 45, "high", "Chewing holes plus visible green caterpillars is a direct, unambiguous identification.",
     "Kale", "Cabbage white caterpillar damage, currently light to moderate.",
     [{"name": "Caterpillar damage", "severity": "high", "evidence": "holes in leaves with green caterpillars underneath"}],
     [{"action": "Pick off caterpillars by hand daily", "priority": "high", "details": "check leaf undersides and growing tips"},
      {"action": "Net the plants with fine mesh", "priority": "high", "details": "stops the butterflies laying more eggs"},
      {"action": "Spray Dipel (Bt) if numbers stay high", "priority": "medium", "details": "targets caterpillars only"}],
     []),
    ("Carrot row", "Germination was patchy and seedlings are thin and pale.",
     "at_risk", 50, "low", "Patchy germination and pale seedlings could be soil crusting, old seed, or a nutrient issue.",
     "Carrot", "Establishment problem rather than a disease; too early to judge the crop.",
     [{"name": "Patchy germination", "severity": "medium", "evidence": "germination was patchy"},
      {"name": "Pale thin seedlings", "severity": "low", "evidence": "seedlings are thin and pale"}],
     [{"action": "Keep the surface moist until seedlings are established", "priority": "high", "details": "cover with hessian or boards until they emerge"},
      {"action": "Thin to 3–4 cm spacing", "priority": "medium", "details": "reduces competition"}],
     ["Seed age", "Soil preparation"]),
    ("Snow pea on the climbing frame", "Vigorous, flowering well, first pods forming. No issues.",
     "healthy", 92, "high", "Detailed description of vigorous, productive growth with no symptoms.",
     "Snow pea", "Thriving; keep picking to extend cropping.",
     [],
     [{"action": "Pick pods young and often", "priority": "low", "details": "regular picking keeps the plant flowering"}],
     []),
    ("Mint (spreading in bed)", "Rust-coloured pustules on the undersides of many leaves.",
     "unhealthy", 30, "high", "Orange pustules on leaf undersides are the classic sign of mint rust.",
     "Mint", "Mint rust, fairly widespread.",
     [{"name": "Mint rust", "severity": "high", "evidence": "rust-coloured pustules on leaf undersides"}],
     [{"action": "Cut the plant to the ground and bin the top growth", "priority": "high", "details": "do not compost"},
      {"action": "Improve airflow and avoid overhead watering", "priority": "medium", "details": "rust needs leaf wetness"},
      {"action": "Consider replacing with fresh, clean stock", "priority": "low", "details": "rust can persist in the roots"}],
     []),
    ("Unknown seedling in the nursery bed", "A seedling I didn't plant — two rounded leaves, reddish stem.",
     "unknown", None, "low", "A very early seedling with only cotyledons is not enough to identify or assess.",
     None, "Not enough information to identify the plant or judge its health.",
     [],
     [],
     ["A photo once the first true leaves appear", "Where in the garden it came up"]),
]


def _fake_trace(question: str, answer: str, run_id: str) -> list[dict]:
    ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    common = {"run_id": run_id, "service": "health"}
    return [
        {"ts": ts, "phase": "plan", "elapsed_ms": 0, "question": question, **common},
        {"ts": ts, "phase": "act", "elapsed_ms": 1100, "iteration": 1,
         "carried_feedback": "(none)", "draft": answer, "draft_chars": len(answer), **common},
        {"ts": ts, "phase": "observe", "elapsed_ms": 1600, "iteration": 1,
         "verdict": "approved", "issues": "(none)", **common},
        {"ts": ts, "phase": "adapt", "elapsed_ms": 1600, "iteration": 1, "decision": "accept", **common},
    ]


def _seed_chat(assessment_id: int) -> None:
    for i, (question, answer) in enumerate(DEMO_CHAT):
        user = AssessmentChatMessage(assessment_id=assessment_id, role="user", content=question)
        assistant = AssessmentChatMessage(
            assessment_id=assessment_id, role="assistant", content=answer
        )
        db.session.add_all([user, assistant])
        db.session.flush()
        run_id = f"health-seed-{i + 1:02d}"
        db.session.add(
            AssessmentAILoopRun(
                assessment_id=assessment_id,
                message_id=assistant.id,
                run_id=run_id,
                question=question,
                final_answer=answer,
                iterations=1,
                verdict="approved",
                transcript_path=f"tools/ai-loop/logs/reports/health/{run_id}.md",
                trace=_fake_trace(question, answer, run_id),
            )
        )


def seed_demo_data() -> None:
    if Assessment.query.first() is not None:
        return

    first_id = None
    for plant_ref, description, status, score, confidence, reason, ident, summary, issues, recs, missing in _SEED:
        assessment = Assessment.from_result(
            {
                "status": status,
                "health_score": score,
                "score_band": describe_score(score),
                "confidence": confidence,
                "confidence_reason": reason,
                "plant_identification": ident,
                "summary": summary,
                "issues": issues,
                "recommendations": recs,
                "missing_information": missing,
            },
            model="seed-data",
            plant_ref=plant_ref,
            description=description,
            has_image=False,
            image_mime=None,
        )
        db.session.add(assessment)
        db.session.flush()
        if first_id is None:
            first_id = assessment.id

    _seed_chat(first_id)
    db.session.commit()

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from reviewer import review_result

case = json.loads(Path(__file__).with_name("reviewer_regression.json").read_text())
plan = case["plan"]
evidence = case["evidence"]
checks = []
bad = review_result(plan, case["result"], evidence)
print("BAD", json.dumps(bad), flush=True)
checks.append(
    (
        "unsupported generic sunlight",
        any("sun" in s.lower() and "tomato:record" in s for s in bad["issues"]),
    )
)
checks.append(
    (
        "wrong cultivar warning",
        any("krim" in s.lower() and "unverified" in s.lower() for s in bad["issues"]),
    )
)
checks.append(("unused citation", any("unused" in s.lower() for s in bad["issues"])))
good = {
    "answer": "Sweet 1000: full sun, moderate water needs, heavy feeder. These are general tomato guidelines, not verified cultivar traits. Black Krim: full sun, high water needs, heavy feeder; provide a sturdy stake or cage and tie stems loosely. General Tomato: planting months January and September–December; sunlight and water needs not recorded.",
    "cited_chunk_ids": [p["chunk_id"] for p in evidence["passages"][:3]],
    "insufficient_context": False,
}
r = review_result(plan, good, evidence)
print("GOOD", json.dumps(r), flush=True)
checks.append(("supported comparison", r == {"recommendation": "accept", "issues": []}))
print("CHECKS", checks, flush=True)

sys.exit(0 if all(ok for _, ok in checks) else 1)

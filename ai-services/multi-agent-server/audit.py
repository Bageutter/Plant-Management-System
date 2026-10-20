import json
import os
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean

import store

STAGES = {"planning": "working", "working": "reviewing", "reviewing": "awaiting_human_review"}
ROLES = {"planning": "planner", "working": "worker", "reviewing": "reviewer"}
DECISIONS = {"accepted", "partially_accepted", "rejected"}


def records(snapshot):
    tasks = {row["id"]: row["task"] for row in snapshot["workflows"]}
    runs = {}
    history, audit = [], []
    previous_states = {}
    for event in snapshot["events"]:
        workflow_id = event["workflow_id"]
        details = event["details"]
        if event["status"] == "planning":
            runs[workflow_id] = {
                "run_id": details.get("run_id") or f"legacy-{event['sequence']}",
                "models": details.get("models", {}),
            }
        run = runs.get(workflow_id, {"run_id": None, "models": {}})
        record = {**event, "task": tasks.get(workflow_id), **run}
        history.append(record)
        role = {
            "working": "planner",
            "reviewing": "worker",
            "awaiting_human_review": "reviewer",
        }.get(event["status"])
        failed_role = (
            ROLES.get(previous_states.get(workflow_id)) if event["status"] == "failed" else None
        )
        audit.append(
            {
                "sequence": event["sequence"],
                "workflow_id": workflow_id,
                "run_id": run["run_id"],
                "created_at": event["created_at"],
                "event": event["status"],
                "completed_role": role,
                "failed_role": failed_role,
                "model": run["models"].get(role or failed_role),
                "decision": details.get("human_review") or details.get("review"),
                "error": details.get("error"),
                "models": run["models"] if event["status"] == "planning" else None,
            }
        )
        previous_states[workflow_id] = event["status"]
    return history, audit


def jsonl(rows):
    return "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)


def export_audit(directory=None):
    snapshot = store.read_snapshot()
    history, decisions = records(snapshot)
    destination = Path(directory) if directory else store.DATABASE.parent
    destination.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, rows in [
        ("workflow_history.jsonl", history),
        ("coordination_audit.jsonl", decisions),
    ]:
        # Replace complete files, rather than append duplicate exports.
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=destination, delete=False
        ) as temp:
            temp.write(jsonl(rows))
            temporary_path = Path(temp.name)
        path = destination / name
        try:
            os.replace(temporary_path, path)
        finally:
            temporary_path.unlink(missing_ok=True)
        paths.append(str(path))
    return {"files": paths, "events": len(history)}


def ratio(numerator, denominator, definition):
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": numerator / denominator if denominator else None,
        "definition": definition,
    }


def seconds(start, end):
    return round((datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds(), 6)


def metrics(snapshot=None):
    snapshot = store.read_snapshot() if snapshot is None else snapshot
    grouped = defaultdict(list)
    for event in snapshot["events"]:
        grouped[event["workflow_id"]].append(event)
    counts = Counter(event["status"] for event in snapshot["events"])
    starts = sum(counts[state] for state in STAGES)
    successes = sum(counts[state] for state in STAGES.values())
    durations = defaultdict(list)
    completed_runs = []
    end_to_end = []
    revision_runs = 0
    for workflow_id, events in grouped.items():
        run_start = None
        stage_start = None
        times = {}
        previous = None
        for event in events:
            if event["status"] == "planning":
                run_start = event
                times = {}
                if previous and previous["status"] == "changes_requested":
                    revision_runs += 1
            if stage_start and event["status"] == STAGES[stage_start["status"]]:
                stage = stage_start["status"]
                duration = seconds(stage_start["created_at"], event["created_at"])
                durations[ROLES[stage]].append(duration)
                times[ROLES[stage]] = duration
            stage_start = event if event["status"] in STAGES else None
            if event["status"] == "awaiting_human_review" and run_start:
                completed_runs.append(
                    {
                        "workflow_id": workflow_id,
                        "run_id": run_start["details"].get("run_id")
                        or f"legacy-{run_start['sequence']}",
                        "finished_at": event["created_at"],
                        "seconds_to_human_review": seconds(
                            run_start["created_at"], event["created_at"]
                        ),
                        "stage_seconds": dict(times),
                    }
                )
            if event["status"] in DECISIONS:
                end_to_end.append(
                    {
                        "workflow_id": workflow_id,
                        "decision": event["status"],
                        "seconds": seconds(events[0]["created_at"], event["created_at"])
                        if events[0]["status"] == "received"
                        else None,
                    }
                )
            previous = event
    reviews = [
        e["details"]["review"]
        for e in snapshot["events"]
        if e["status"] == "awaiting_human_review" and "review" in e["details"]
    ]
    issues = sum(len(review.get("issues", [])) for review in reviews)
    current = Counter(row["status"] for row in snapshot["workflows"] if row["id"] in grouped)
    tracked = len(grouped)
    attempts = counts["planning"]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "Local development history, including failures and interrupted runs; not a benchmark.",
        "tracked_workflows": tracked,
        "untracked_legacy_workflows": len(snapshot["workflows"]) - tracked,
        "run_attempts": attempts,
        "current_states": dict(current),
        "plan_acceptance_rate": {
            "value": None,
            "reason": "No separate plan-approval decision is recorded.",
        },
        "plan_generation_rate": ratio(
            counts["working"], attempts, "Runs producing a plan / runs started"
        ),
        "worker_completion_rate": ratio(
            counts["reviewing"], counts["working"], "Worker results saved / Worker starts"
        ),
        "handoff_success_rate": ratio(
            successes,
            starts,
            "Completed AI stages / started AI stages; includes pending and interrupted starts",
        ),
        "reviewer_defect_yield": {
            "issues_reported": issues,
            "reviews": len(reviews),
            "issues_per_review": issues / len(reviews) if reviews else None,
            "reviews_with_issues": sum(bool(review.get("issues")) for review in reviews),
            "confirmed_defects": None,
            "note": "Reported issues are not confirmed defects. Ground-truth regression results are separate.",
        },
        "rework_ratio": ratio(
            max(
                0,
                attempts
                - sum(any(e["status"] == "planning" for e in es) for es in grouped.values()),
            ),
            attempts,
            "Repeat runs / all runs; includes failure retries",
        ),
        "human_requested_revision_runs": revision_runs,
        "workflow_completion_rate": ratio(
            sum(current[state] for state in DECISIONS),
            tracked,
            "Workflows with a final human decision / tracked workflows; rejection counts as closed",
        ),
        "human_approval_rate": ratio(
            current["accepted"] + current["partially_accepted"],
            tracked,
            "Accepted or partially accepted workflows / tracked workflows",
        ),
        "end_to_end_completion_times": end_to_end,
        "end_to_end_note": "Creation to final decision, including human waiting time; pending workflows have no completion duration.",
        "stage_execution_times": {
            role: {
                "samples": len(durations[role]),
                "mean_seconds": round(mean(durations[role]), 6) if durations[role] else None,
                "successful_seconds": durations[role],
            }
            for role in ROLES.values()
        },
        "latest_agent_run": max(completed_runs, key=lambda run: run["finished_at"])
        if completed_runs
        else None,
    }


if __name__ == "__main__":
    print(json.dumps(export_audit(), indent=2))

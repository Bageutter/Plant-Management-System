import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import store
from app import app
from audit import export_audit, metrics, records


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patch = patch.object(store, "DATABASE", Path(self.temp.name) / "workflows.db")
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def test_exports_are_complete_and_repeatable(self):
        store.save_workflow("one", "Check a plant")
        store.transition(
            "one",
            "received",
            "planning",
            {
                "run_id": "run-1",
                "models": {"planner": "qwen", "worker": "qwen", "reviewer": "llama"},
            },
        )
        store.transition("one", "planning", "working", {"plan": {"steps": ["Retrieve"]}})
        store.transition(
            "one",
            "working",
            "reviewing",
            {"result": {"answer": "Full sun"}, "evidence": {"passages": []}},
        )
        store.transition(
            "one",
            "reviewing",
            "awaiting_human_review",
            {"review": {"recommendation": "accept", "issues": []}},
        )
        store.transition(
            "one",
            "awaiting_human_review",
            "accepted",
            {"human_review": {"decision": "accept", "reviewer_id": "test"}},
        )
        first = export_audit()
        data = [Path(p).read_text() for p in first["files"]]
        export_audit()
        self.assertEqual(data, [Path(p).read_text() for p in first["files"]])
        history, audit = [[json.loads(line) for line in text.splitlines()] for text in data]
        self.assertEqual(len(history), 6)
        self.assertEqual(history[3]["details"]["result"]["answer"], "Full sun")
        self.assertEqual(history[3]["run_id"], "run-1")
        self.assertEqual(audit[4]["model"], "llama")
        self.assertEqual(audit[5]["decision"]["reviewer_id"], "test")
        response = app.test_client().get("/workflow/audit/coordination_audit.jsonl")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text, data[1])
        self.assertEqual(app.test_client().get("/workflow/audit/other").status_code, 404)

    def test_empty_metrics_do_not_claim_success(self):
        result = metrics()
        self.assertEqual(result["tracked_workflows"], 0)
        self.assertIsNone(result["worker_completion_rate"]["value"])
        self.assertIsNone(result["latest_agent_run"])

    def test_metrics_distinguish_retry_review_and_human_completion(self):
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        events = []

        def event(status, second, details=None):
            events.append(
                {
                    "sequence": len(events) + 1,
                    "workflow_id": "one",
                    "status": status,
                    "details": details or {},
                    "created_at": (start + timedelta(seconds=second)).isoformat(),
                }
            )

        event("received", 0)
        event("planning", 1)
        event("working", 3)
        event("failed", 4)
        event("planning", 5)
        event("working", 8)
        event("reviewing", 12)
        event(
            "awaiting_human_review",
            18,
            {"review": {"recommendation": "revise", "issues": ["unsupported claim"]}},
        )
        snapshot = {
            "events": events,
            "workflows": [{"id": "one", "task": "Task", "status": "awaiting_human_review"}],
        }
        result = metrics(snapshot)
        self.assertEqual(result["worker_completion_rate"]["value"], 0.5)
        self.assertEqual(result["handoff_success_rate"]["value"], 4 / 5)
        self.assertEqual(result["rework_ratio"]["value"], 0.5)
        self.assertEqual(result["workflow_completion_rate"]["value"], 0)
        self.assertEqual(
            result["latest_agent_run"]["stage_seconds"], {"planner": 3, "worker": 4, "reviewer": 6}
        )
        self.assertEqual(result["reviewer_defect_yield"]["issues_reported"], 1)
        self.assertIsNone(result["reviewer_defect_yield"]["confirmed_defects"])
        event("partially_accepted", 25)
        snapshot["workflows"][0]["status"] = "partially_accepted"
        result = metrics(snapshot)
        self.assertEqual(result["workflow_completion_rate"]["value"], 1)
        self.assertEqual(result["end_to_end_completion_times"][0]["seconds"], 25)
        self.assertIsNone(records(snapshot)[0][1]["models"].get("planner"))

    def test_recovery_preserves_live_owner_and_waiting_review(self):
        for id in ["dead", "alive", "waiting"]:
            store.save_workflow(id, "Task")
            store.transition(id, "received", "planning", {"owner_pid": os.getpid()})
        store.transition("waiting", "planning", "working", {})
        store.transition("waiting", "working", "reviewing", {})
        store.transition("waiting", "reviewing", "awaiting_human_review", {})
        with patch("store.os.kill", side_effect=[ProcessLookupError(), None]):
            recovered = store.recover_interrupted()
        self.assertEqual(recovered, ["dead"])
        self.assertEqual(store.get_workflow("dead")["status"], "failed")
        self.assertEqual(store.get_workflow("alive")["status"], "planning")
        self.assertEqual(store.get_workflow("waiting")["status"], "awaiting_human_review")
        self.assertEqual(
            store.get_workflow("dead")["history"][-1]["details"]["interrupted_stage"], "planning"
        )

    def test_legacy_interrupted_run_recovers_without_inventing_models(self):
        store.save_workflow("old", "Task")
        store.transition("old", "received", "planning", {})
        self.assertEqual(store.recover_interrupted(), ["old"])
        history, _ = records(store.read_snapshot())
        self.assertEqual(history[1]["models"], {})


if __name__ == "__main__":
    unittest.main()

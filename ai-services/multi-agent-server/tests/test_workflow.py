import sqlite3
from contextlib import closing
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import store
from app import app


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.database = patch.object(store, "DATABASE", Path(self.directory.name) / "workflows.db")
        self.database.start()
        self.client = app.test_client()
        self.plan = {"steps": ["Retrieve tomato evidence"]}
        self.output = {"result": {"answer": "Tomato: full sun", "insufficient_context": False,
                                  "cited_chunk_ids": ["tomato"]},
                       "evidence": {"passages": [{"chunk_id": "tomato", "text": "Full sun"}]}}
        self.patches = [patch("workflow.create_plan", return_value=self.plan),
                        patch("workflow.run_worker", return_value=self.output),
                        patch("workflow.review_result", return_value={"recommendation": "accept", "issues": []})]
        self.planner, self.worker, self.reviewer = [p.start() for p in self.patches]
        self.id = self.client.post("/workflow", json={"task": "Tomato care"}).json["workflow_id"]

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.database.stop()
        self.directory.cleanup()

    def run_flow(self):
        return self.client.post("/workflow/run", json={"workflow_id": self.id})

    def decide(self, decision, feedback=""):
        return self.client.post("/workflow/review", json={"workflow_id": self.id,
                                "decision": decision, "feedback": feedback, "reviewer_id": "Amy"})

    def test_run_records_model_roles(self):
        with patch.dict('os.environ', {'OLLAMA_MODEL': 'test-qwen', 'REVIEWER_MODEL': 'test-llama'}):
            response = self.run_flow()
        self.assertEqual(response.json['models'], {
            'planner': 'test-qwen', 'worker': 'test-qwen', 'reviewer': 'test-llama'})
        self.assertTrue(response.json['run_id'])
        self.assertIsInstance(response.json['owner_pid'], int)

    def test_accept_persists_output_and_history(self):
        response = self.run_flow()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["status"], "awaiting_human_review")
        self.assertEqual(self.decide("accept").json["status"], "accepted")
        saved = self.client.get("/workflow/status", query_string={"id": self.id}).json
        self.assertEqual(saved["plan"], self.plan)
        self.assertEqual(saved["result"], self.output["result"])
        self.assertEqual(saved["evidence"], self.output["evidence"])
        self.assertEqual(saved["human_review"]["reviewer_id"], "Amy")
        self.assertEqual([e["status"] for e in saved["history"]],
                         ["received", "planning", "working", "reviewing", "awaiting_human_review", "accepted"])
        self.assertEqual(self.decide("reject").status_code, 409)
        self.assertEqual(self.run_flow().status_code, 409)

    def test_partial_acceptance_requires_feedback_and_saves_conditions(self):
        self.run_flow()
        for feedback in ("", "   "):
            self.assertEqual(self.decide("partially_accept", feedback).status_code, 400)
        self.assertEqual(store.get_workflow(self.id)["status"], "awaiting_human_review")
        feedback = "Accept sunlight information; watering frequency remains unsupported"
        response = self.decide("partially_accept", feedback)
        self.assertEqual(response.status_code, 200)
        saved = self.client.get("/workflow/status", query_string={"id": self.id}).json
        self.assertEqual(saved["status"], "partially_accepted")
        self.assertEqual(saved["human_review"], {"decision": "partially_accept",
                         "feedback": feedback, "reviewer_id": "Amy"})
        self.assertEqual(saved["history"][-1]["status"], "partially_accepted")
        self.assertTrue(saved["history"][-1]["created_at"])
        self.assertEqual(self.decide("accept").status_code, 409)
        self.assertEqual(self.run_flow().status_code, 409)

    def test_changes_feed_next_plan_and_preserve_previous_review(self):
        self.run_flow()
        self.assertEqual(self.decide("request_changes").status_code, 400)
        self.assertEqual(self.decide("request_changes", "Compare water needs").status_code, 200)
        response = self.run_flow()
        self.assertIn("Compare water needs", self.planner.call_args.args[0])
        self.assertEqual(self.worker.call_args.kwargs["feedback"], "Compare water needs")
        self.assertNotIn("human_review", response.json)
        self.assertTrue(any(e["status"] == "changes_requested" for e in response.json["history"]))
        self.assertEqual(self.decide("reject").json["status"], "rejected")

    def test_failure_is_saved_and_can_retry(self):
        self.worker.side_effect = RuntimeError("private upstream error")
        with self.assertLogs(level="ERROR"):
            response = self.run_flow()
        self.assertEqual(response.status_code, 502)
        self.assertNotIn("private", str(response.json))
        self.assertEqual(store.get_workflow(self.id)["status"], "failed")
        self.assertEqual(self.decide("accept").status_code, 409)
        self.worker.side_effect = None
        self.assertEqual(self.run_flow().json["status"], "awaiting_human_review")

    def test_invalid_and_out_of_order_requests(self):
        self.assertEqual(self.decide("accept").status_code, 409)
        self.assertEqual(self.client.post("/workflow/run", json={}).status_code, 400)
        self.assertEqual(self.client.post("/workflow/run", json={"workflow_id": "missing"}).status_code, 404)
        self.run_flow()
        for decision in ("approve", [], None):
            self.assertEqual(self.decide(decision).status_code, 400)
        self.assertEqual(self.run_flow().status_code, 409)

    def test_ai_revise_requires_human_override_reason(self):
        self.reviewer.return_value = {"recommendation": "revise", "issues": ["Unsupported sun claim"]}
        self.run_flow()
        self.assertEqual(self.decide("accept").status_code, 400)
        self.assertEqual(self.decide("accept", "Checked the original source").status_code, 200)

    def test_only_one_run_can_claim_the_workflow(self):
        store.transition(self.id, "received", "planning", {})
        with self.assertRaises(store.WorkflowConflict):
            store.transition(self.id, "received", "planning", {})
        self.assertEqual(self.run_flow().status_code, 409)

    def test_revision_feedback_survives_failed_retry(self):
        self.run_flow()
        self.decide("request_changes", "Include soil requirements")
        self.worker.side_effect = RuntimeError("offline")
        with self.assertLogs(level="ERROR"):
            self.run_flow()
        self.worker.side_effect = None
        self.run_flow()
        self.assertIn("Include soil requirements", self.planner.call_args.args[0])

    def test_existing_database_is_preserved(self):
        with closing(sqlite3.connect(store.DATABASE)) as connection:
            connection.execute("DROP TABLE workflow_events")
            connection.commit()
        self.assertEqual(store.get_workflow(self.id)["task"], "Tomato care")
        self.assertEqual(self.run_flow().status_code, 200)


if __name__ == "__main__":
    unittest.main()

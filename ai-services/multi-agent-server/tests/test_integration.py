"""application_integration: the helper feature backends and the terminal use to hand a
task (with its evidence) to this server and record the human decision."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import application_integration as integration
import store
from app import app

HEALTH = {"mode": "health-api", "passages": [
    {"chunk_id": "health-history", "title": "Tomato history — Plant Health record",
     "text": "Plant: Tomato\nAssessments recorded: 1 (newest first: Assessment 7 at risk 45)"},
    {"chunk_id": "health-7", "title": "Assessment 7 Tomato — Plant Health record",
     "text": "Status: at risk; health score 45/100\nIssues: Overwatering (medium) - Soil stays wet"},
]}


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.database = patch.object(store, "DATABASE", Path(self.directory.name) / "workflows.db")
        self.database.start()
        self.client = app.test_client()
        result = {"answer": "Assessment 7 Tomato: at risk, health score 45/100, overwatering.",
                  "insufficient_context": False, "cited_chunk_ids": ["health-7"]}
        self.patches = [patch("workflow.create_plan", return_value={"steps": ["Read the assessments"]}),
                        patch("worker.execute_plan", return_value=result),
                        patch("worker._retrieve_context"),
                        patch("workflow.review_result", return_value={"recommendation": "accept", "issues": []})]
        self.planner, self.worker, self.retrieve, self.reviewer = [p.start() for p in self.patches]

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.database.stop()
        self.directory.cleanup()

    def request(self, method, path, payload=None, timeout=None):
        """Route the helper's HTTP calls into the Flask app under test."""
        response = self.client.open(path, method=method, json=payload)
        return response.status_code, response.get_json()

    def test_submit_runs_the_agents_and_review_records_the_decision(self):
        state = integration.submit_task("health", "  How is the tomato?  ", HEALTH, request=self.request)
        self.assertEqual(state["status"], "awaiting_human_review")
        self.assertEqual(state["source"], "health")
        self.assertEqual(state["task"], "How is the tomato?")
        self.assertEqual(state["evidence"], HEALTH)
        self.assertEqual(state["result"]["cited_chunk_ids"], ["health-7"])
        self.assertEqual(self.planner.call_args.kwargs["source"], "health")
        self.assertEqual(self.worker.call_args.args[3], "health")
        self.retrieve.assert_not_called()  # the server never reads health data itself

        reviewed = integration.review_task(state["workflow_id"], "accept", "Checked the records",
                                           reviewer_id="guhan-terminal", request=self.request)
        self.assertEqual(reviewed["status"], "accepted")
        self.assertEqual(reviewed["human_review"]["reviewer_id"], "guhan-terminal")
        self.assertEqual([e["status"] for e in reviewed["history"]],
                         ["received", "planning", "working", "reviewing", "awaiting_human_review", "accepted"])
        self.assertEqual(integration.workflow_status(state["workflow_id"], request=self.request)["status"],
                         "accepted")

    def test_create_without_running_and_almanac_without_evidence(self):
        created = integration.submit_task("almanac", "Tomato sun needs", run=False, request=self.request)
        self.assertEqual(created["status"], "received")
        self.assertEqual(created["source"], "almanac")
        self.planner.assert_not_called()

    def test_client_side_validation_sends_nothing(self):
        bad = [
            dict(feature="weather", task="x", evidence=HEALTH),
            dict(feature="health", task="", evidence=HEALTH),
            dict(feature="health", task="x" * 501, evidence=HEALTH),
            dict(feature="health", task="x", evidence=None),
            dict(feature="vgarden", task="x", evidence=None),
            dict(feature="health", task="x", evidence={"passages": "no"}),
        ]
        for kwargs in bad:
            with self.assertRaises(ValueError, msg=kwargs):
                integration.submit_task(request=self.request, **kwargs)
        with self.assertRaises(ValueError):
            integration.review_task("id", "approve", request=self.request)
        self.assertEqual(store.read_snapshot()["workflows"], [])

    def test_server_refusals_become_server_errors(self):
        empty = {"mode": "health-api", "passages": []}
        with self.assertRaises(integration.ServerError) as refused:
            integration.submit_task("health", "x", empty, request=self.request)
        self.assertEqual(refused.exception.status, 400)
        self.assertIn("1 to 10 passages", str(refused.exception))
        with self.assertRaises(integration.ServerError) as missing:
            integration.review_task("missing", "accept", request=self.request)
        self.assertEqual(missing.exception.status, 404)

    def test_http_transport_validates_the_url_and_reports_an_unreachable_server(self):
        with self.assertRaises(ValueError):
            integration.server_url("ftp://agents")
        with self.assertRaises(integration.ServerError):
            integration.http_request("GET", "/healthz", base_url="http://127.0.0.1:1", timeout=1)

    def test_terminal_entry_point(self):
        evidence = Path(self.directory.name) / "evidence.json"
        evidence.write_text(json.dumps(HEALTH))
        with patch("application_integration.http_request",
                   side_effect=lambda m, p, payload=None, base_url=None, timeout=15: self.request(m, p, payload)):
            with patch("sys.stdout") as out:
                code = integration.main(["health", "How is the tomato?", str(evidence)])
        self.assertEqual(code, 0)
        printed = "".join(call.args[0] for call in out.write.call_args_list)
        self.assertIn('"status": "awaiting_human_review"', printed)
        workflow_id = json.loads(printed)["workflow_id"]
        with patch("application_integration.http_request",
                   side_effect=lambda m, p, payload=None, base_url=None, timeout=15: self.request(m, p, payload)):
            with patch("sys.stdout"):
                self.assertEqual(integration.main(["--review", workflow_id, "partially_accept",
                                                   "Scores", "unverified", "--reviewer", "guhan"]), 0)
        self.assertEqual(store.get_workflow(workflow_id)["human_review"],
                         {"decision": "partially_accept", "feedback": "Scores unverified", "reviewer_id": "guhan"})
        with patch("sys.stderr"):
            self.assertEqual(integration.main(["health", "no evidence given"]), 1)


if __name__ == "__main__":
    unittest.main()

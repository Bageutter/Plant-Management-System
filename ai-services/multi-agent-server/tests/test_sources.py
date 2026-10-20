"""Feature sources: the Almanac Worker retrieves public references through MCP,
while Virtual Garden must supply its one garden's private records with the task."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import store
from app import app
from planner import create_plan
from worker import execute_plan, run_worker

GARDEN = {"mode": "mcp:get_garden_snapshot", "passages": [
    {"chunk_id": "garden-1-plantings", "title": "Backyard plantings — Virtual Garden record",
     "text": "Tomato ×3 — growing, flowering at area: North bed, planted 2026-09-01."},
]}


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.database = patch.object(store, "DATABASE", Path(self.directory.name) / "workflows.db")
        self.database.start()
        self.client = app.test_client()

    def tearDown(self):
        self.database.stop()
        self.directory.cleanup()

    def create(self, **body):
        return self.client.post("/workflow", json={"task": "What is growing?", **body})

    def test_default_source_is_almanac_without_evidence(self):
        response = self.create()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json["source"], "almanac")
        saved = store.get_workflow(response.json["workflow_id"])
        self.assertEqual(saved["source"], "almanac")
        self.assertEqual(saved["history"][0]["details"], {"source": "almanac"})

    def test_vgarden_requires_valid_supplied_evidence(self):
        bad = [
            {"source": "weather"},
            {"source": "vgarden"},
            {"source": "vgarden", "evidence": {"passages": []}},
            {"source": "vgarden", "evidence": {"passages": [{"chunk_id": "a", "title": "t"}]}},
            {"source": "vgarden", "evidence": {"passages": [GARDEN["passages"][0]] * 2}},
            {"source": "vgarden", "evidence": {"passages": [{**GARDEN["passages"][0], "text": "x" * 4001}]}},
        ]
        for body in bad:
            self.assertEqual(self.create(**body).status_code, 400, body)
        self.assertEqual(store.read_snapshot()["workflows"], [])

    def test_vgarden_evidence_is_stored_and_reaches_the_agents(self):
        extra = {**GARDEN["passages"][0], "owner_id": 7}
        response = self.create(source="vgarden", evidence={**GARDEN, "passages": [extra]})
        workflow_id = response.json["workflow_id"]
        self.assertEqual(store.get_workflow(workflow_id)["history"][0]["details"],
                         {"source": "vgarden", "evidence": GARDEN})  # unknown keys dropped
        result = {"answer": "Backyard plantings: Tomato ×3, flowering.",
                  "insufficient_context": False, "cited_chunk_ids": ["garden-1-plantings"]}
        with patch("workflow.create_plan", return_value={"steps": ["Read plantings"]}) as plan, \
                patch("worker.execute_plan", return_value=result) as act, \
                patch("worker._retrieve_context") as retrieve, \
                patch("workflow.review_result", return_value={"recommendation": "accept", "issues": []}):
            ran = self.client.post("/workflow/run", json={"workflow_id": workflow_id})
        self.assertEqual(ran.status_code, 200)
        self.assertEqual(ran.json["status"], "awaiting_human_review")
        self.assertEqual(plan.call_args.kwargs["source"], "vgarden")
        self.assertEqual(act.call_args.args[1], GARDEN)
        self.assertEqual(act.call_args.args[3], "vgarden")
        retrieve.assert_not_called()  # private garden data is never fetched by this server
        self.assertEqual(ran.json["evidence"], GARDEN)

    def test_worker_refuses_vgarden_without_evidence(self):
        with self.assertRaises(ValueError):
            run_worker("What is growing?", {"steps": ["Read"]}, source="vgarden")

    def test_prompts_are_framed_per_source(self):
        captured = []

        class Reply:
            def __init__(self, content):
                self.content = content

            def raise_for_status(self):
                pass

            def json(self):
                return {"message": {"content": self.content}}

        def fake_post(url, json, timeout):
            captured.append(json["messages"][0]["content"])
            cited = "garden-1-plantings" if "garden" in captured[-1] else "t"
            return Reply('{"answer": "Recorded.", "insufficient_context": false, '
                         f'"cited_chunk_ids": ["{cited}"]}}')

        with patch("worker.httpx.post", side_effect=fake_post):
            execute_plan({"steps": ["Read"]}, GARDEN, "What is growing?", "vgarden")
            execute_plan({"steps": ["Read"]}, {"passages": [{"chunk_id": "t", "title": "Tomato — ref",
                         "text": "Sun needs: full sun"}]}, "Tomato sun?", "almanac")
        self.assertIn("this one garden", captured[0])
        self.assertIn("requested plant", captured[1])
        self.assertNotIn("REQUESTED_CHANGES", captured[0] + captured[1])
        with self.assertRaises(ValueError):
            create_plan("Plan", source="weather")

    def test_revised_run_gives_the_worker_the_requested_changes(self):
        sent = {}

        def fake_post(url, json, timeout):
            sent.update(system=json["messages"][0]["content"], user=json["messages"][1]["content"])
            reply = Mock()
            reply.json.return_value = {"message": {"content": '{"answer": "Recorded.", '
                                       '"insufficient_context": false, "cited_chunk_ids": ["garden-1-plantings"]}'}}
            return reply

        with patch("worker.httpx.post", side_effect=fake_post):
            execute_plan({"steps": ["Read"]}, GARDEN, "What is flowering?", "vgarden",
                         "Also give the tomato count")
        self.assertIn("REQUESTED_CHANGES", sent["system"])
        self.assertIn('"requested_changes": "Also give the tomato count"', sent["user"])


if __name__ == "__main__":
    unittest.main()

"""Unit tests for the local AI feature reviewer.

These tests use fake data. They do not call Ollama or change project files.
"""

import importlib.util
import tempfile
import unittest
from pathlib import Path


# Load the pipeline directly because its folder name contains a hyphen.
PIPELINE_PATH = Path(__file__).resolve().parents[1] / "pipeline.py"
SPEC = importlib.util.spec_from_file_location("ai_dev", PIPELINE_PATH)
pipeline = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(pipeline)


def example_finding(path="vgarden/app.py"):
    """Return one small, valid recommendation for use in tests."""
    return {
        "title": "Clarify an error message",
        "summary": "The current message is unclear.",
        "recommendation": "Use a clearer message.",
        "evidence": [{"path": path, "observation": "The route says error."}],
        "file_recommendations": [
            {"path": path, "suggestion": "Explain what the user can do next."}
        ],
        "checks": ["Open the route and inspect the message."],
        "risks": [],
    }


class PipelineTests(unittest.TestCase):
    def test_uses_the_expected_models(self):
        self.assertEqual(pipeline.FINDING_MODEL, "qwen3:4b-instruct")
        self.assertEqual(pipeline.REVIEW_MODEL, "llama3.1:8b")

    def test_reads_code_but_ignores_secrets_and_generated_files(self):
        self.assertTrue(pipeline.is_discovery_path("almanac/app.py"))
        self.assertFalse(pipeline.is_discovery_path("almanac/.env"))
        self.assertFalse(pipeline.is_discovery_path("shared/frontend/venv/bin/flask"))
        self.assertFalse(pipeline.is_discovery_path("assets/model.glb"))

    def test_only_reads_the_selected_feature(self):
        self.assertTrue(pipeline.path_in_scope("almanac/app.py", "almanac"))
        self.assertFalse(pipeline.path_in_scope("vgarden/app.py", "almanac"))
        self.assertTrue(
            pipeline.path_in_scope("docker-compose.yml", "architecture")
        )

    def test_accept_and_reject_allow_notes(self):
        accepted_answers = iter(["a", "Looks useful."])
        accepted = pipeline.ask_human_decision(
            lambda _: next(accepted_answers), interactive=True
        )
        self.assertEqual(accepted, {"decision": "accepted", "note": "Looks useful."})

        rejected_answers = iter(["r", "Not supported."])
        rejected = pipeline.ask_human_decision(
            lambda _: next(rejected_answers), interactive=True
        )
        self.assertEqual(rejected, {"decision": "rejected", "note": "Not supported."})

    def test_index_links_to_separate_reports(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            values = {
                "target": "Virtual Garden",
                "context_paths": [Path("vgarden/app.py")],
                "finding": example_finding(),
                "review": {
                    "status": "supported",
                    "summary": "Supported.",
                    "findings": [],
                },
                "decision": {"decision": "accepted", "note": "Looks useful."},
                "models": {"finding": "qwen", "review": "llama"},
                "author": "Amy Z",
            }
            first_id, log_path, first_report = pipeline.create_output_paths(
                repo, "Virtual Garden", "Amy Z"
            )
            pipeline.write_review_files(
                first_id, log_path, first_report, **values
            )
            second_id, _, second_report = pipeline.create_output_paths(
                repo, "Virtual Garden", "Amy Z"
            )
            pipeline.write_review_files(
                second_id, log_path, second_report, **values
            )

            log = log_path.read_text(encoding="utf-8")
            self.assertIn("| 1 | Virtual Garden | Amy Z |", log)
            self.assertEqual(log_path.name, "amy_z.md")
            self.assertIn("[Open](reports/amy_z/0002-virtual-garden.md)", log)
            self.assertTrue(first_report.exists())
            self.assertTrue(second_report.exists())


if __name__ == "__main__":
    unittest.main()

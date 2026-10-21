"""Unit tests for the Testing Report Review mode (tools/ai-loop/testing_review.py),
driven with a fake proposer model and a scripted reviewer. No Ollama, no network.

Run from the repository root:
    python -m unittest discover -s tools/ai-loop/tests
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "shared"))
sys.path.insert(0, str(HERE.parent))
import ai_loop  # noqa: E402
import evidence_review as review  # noqa: E402
import review_common as common  # noqa: E402
import testing_review as tr  # noqa: E402

FIXTURES = HERE / "fixtures" / "testing"
PRE = FIXTURES / "pre-commit"
POST = FIXTURES / "post-commit"


class FakeModel:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, system: str, user: str) -> dict:
        self.calls.append((system, json.loads(user)))
        return self.responses[min(len(self.calls) - 1, len(self.responses) - 1)]


class FakeReviewer:
    def __init__(self, *verdicts):
        self.verdicts = list(verdicts) or ["approved"]
        self.drafts: list[dict] = []

    def review(self, question, grounding, draft):
        self.drafts.append(json.loads(draft))
        verdict = self.verdicts[min(len(self.drafts) - 1, len(self.verdicts) - 1)]
        if verdict == "approved":
            return {"verdict": "approved", "issues": [], "guidance": ""}
        return {"verdict": "revise", "issues": ["count not in grounding"], "guidance": "quote the JUnit counts"}


def pass_draft(**overrides) -> dict:
    draft = {
        "decision": "pass",
        "students_reviewed": 1,
        "findings": [],
        "recommendations": ["Keep the endpoint tests named after their functions."],
        "summary": "One pre-commit report and one post-commit run reviewed for vgarden-sample; all checks hold.",
    }
    draft.update(overrides)
    return draft


def finding(**overrides) -> dict:
    base = {"severity": "low", "area": "post_commit", "subject": "vgarden-sample", "evidence": "x", "recommendation": "y"}
    base.update(overrides)
    return base


def checks_for(pre: Path, post: Path) -> list[tuple[str, str, str]]:
    grounding, _ = tr.build_grounding(tr.load_evidence(pre, post))
    return [(c["severity"], c["area"], c["subject"]) for c in grounding["code_checks"]]


def check_pairs(pre: Path, post: Path) -> list[tuple[str, str]]:
    return [(severity, area) for severity, area, _ in checks_for(pre, post)]


class TempCase(unittest.TestCase):
    """A temporary folder per test with a writable copy of the fixture folders."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def evidence_copy(self) -> tuple[Path, Path]:
        pre, post = self.tmp_path / "pre-commit", self.tmp_path / "post-commit"
        shutil.copytree(PRE, pre)
        shutil.copytree(POST, post)
        return pre, post

    def run_loop(self, pre, post, model, reviewer, **kwargs):
        return tr.review(tr.load_evidence(pre, post), tr.TestingDrafter(call_model=model), reviewer, str(self.tmp_path / "logs"), **kwargs)


def rewrite_run_json(folder: Path, **changes) -> None:
    path = folder / "run.json"
    run = json.loads(path.read_text(encoding="utf-8"))
    run.update(changes)
    path.write_text(json.dumps(run), encoding="utf-8")


# --------------------------------------------------------------------------- #
# Loading and parsing                                                         #
# --------------------------------------------------------------------------- #


class ParsingTests(TempCase):
    def test_parses_the_report_py_page(self):
        reports = tr.load_pre_commit_reports(PRE)

        self.assertEqual(len(reports), 1)
        report = reports[0]
        self.assertEqual((report["stem"], report["service"], report["owner"]), ("vgarden-sample", "vgarden", "Sample Student"))
        self.assertEqual(report["generated"], "2026-10-21 08:00 UTC")
        self.assertEqual(set(report["checks"]), set(tr.REQUIRED_CHECKS))
        self.assertEqual(report["checks"]["ruff"], {
            "result": "PASS", "run_at": "2026-10-21 07:58", "commit": "0a31150520", "branch": "sample/branch",
            "scope": "3 file(s)", "findings": "no security findings",
        })
        self.assertEqual(report["checks"]["tests"]["findings"], "41 passed in 12.00s")
        self.assertEqual((report["history_runs"], report["history_failed_runs"]), (5, 1))

    def test_the_readme_is_not_a_report(self):
        pre, _ = self.evidence_copy()
        (pre / "README.md").write_text("# index\n", encoding="utf-8")
        self.assertEqual([r["stem"] for r in tr.load_pre_commit_reports(pre)], ["vgarden-sample"])
        self.assertEqual(tr.load_pre_commit_reports(self.tmp_path / "missing"), [])

    def test_parses_the_ci_artifact_folder(self):
        runs = tr.load_post_commit_runs(POST)

        self.assertEqual(len(runs), 1)
        run = runs[0]
        self.assertEqual((run["stem"], run["event"], run["workflow"]), ("vgarden-sample", "push", "Virtual Garden (Sample)"))
        self.assertEqual(run["workflow_file"], ".github/workflows/vgarden.yml")
        self.assertTrue(run["workflow_file_in_repo"])
        self.assertEqual(run["source_sha"], "0a31150520c0")
        self.assertEqual(run["tested_sha"], "0a31150520c0")
        self.assertEqual(run["endpoint_functions"], {"routes.create_garden": "POST /gardens", "routes.garden_snapshot": "GET /gardens/<id>/snapshot"})
        self.assertEqual((run["endpoint_tests"]["tests"], run["endpoint_tests"]["failures"]), (2, 0))
        self.assertEqual([c["name"] for c in run["endpoint_tests"]["cases"]], [
            "test_create_garden_validates_and_persists", "test_garden_snapshot_is_owner_scoped_and_read_only",
        ])
        self.assertEqual(run["regression_tests"], {"tests": 3, "failures": 0, "errors": 0, "skipped": 1, "failed_cases": ["test_container_crud"]})
        self.assertTrue(run["readme_present"] and run["run_json_present"])

    def test_junit_parsing_reports_failures_and_unreadable_files(self):
        xml = self.tmp_path / "x.xml"
        xml.write_text(
            '<testsuite tests="2" failures="1" errors="0" skipped="0"><testcase name="ok"/>'
            '<testcase name="bad"><failure message="boom"/></testcase></testsuite>',
            encoding="utf-8",
        )
        parsed = tr.parse_junit(xml)
        self.assertEqual(parsed["failures"], 1)
        self.assertEqual([c["outcome"] for c in parsed["cases"]], ["passed", "failure"])

        xml.write_text("<testsuite", encoding="utf-8")
        self.assertTrue(tr.parse_junit(xml)["parse_error"])
        self.assertIsNone(tr.parse_junit(self.tmp_path / "none.xml"))


# --------------------------------------------------------------------------- #
# PLAN: the code checks                                                       #
# --------------------------------------------------------------------------- #


class CodeCheckTests(TempCase):
    def test_the_fixture_evidence_passes_every_code_check(self):
        grounding, plan = tr.build_grounding(tr.load_evidence(PRE, POST))

        self.assertEqual((grounding["code_checks"], grounding["evidence_gaps"]), ([], []))
        self.assertEqual(plan, {
            "pre_commit_reports": 1, "post_commit_runs": 1, "students": 1, "endpoint_tests": 2, "regression_tests": 3,
            "code_findings": "high=0 medium=0 low=0", "evidence_gaps": 0,
        })
        self.assertEqual(grounding["students"], [{"stem": "vgarden-sample", "has_pre_commit": True, "has_post_commit": True}])
        self.assertEqual(set(grounding["required_pre_commit_checks"]), {"ruff", "secrets", "audit", "tests"})

    def test_a_failed_or_missing_required_scan_is_high(self):
        pre, post = self.evidence_copy()
        page = pre / "vgarden-sample.md"
        text = page.read_text(encoding="utf-8")
        text = text.replace("| detect-secrets (`detect-secrets-hook --baseline .secrets.baseline`) | PASS |",
                            "| detect-secrets (`detect-secrets-hook --baseline .secrets.baseline`) | FAIL |")
        text = "\n".join(line for line in text.splitlines() if not line.startswith("| pip-audit"))
        page.write_text(text, encoding="utf-8")

        checks = tr.build_grounding(tr.load_evidence(pre, post))[0]["code_checks"]

        self.assertEqual([(c["severity"], c["area"]) for c in checks], [("high", "pre_commit"), ("high", "pre_commit")])
        self.assertIn("detect-secrets' = FAIL", checks[0]["evidence"])
        self.assertIn("pip-audit dependency vulnerabilities' not run", checks[1]["evidence"])

    def test_a_non_push_run_and_red_tests_are_high(self):
        pre, post = self.evidence_copy()
        folder = post / "vgarden-sample"
        rewrite_run_json(folder, event="pull_request", tested_sha="ffffffffffffffffffffffffffffffffffffffff")
        endpoints = folder / "endpoints.xml"
        endpoints.write_text(
            endpoints.read_text(encoding="utf-8").replace('failures="0"', 'failures="1"').replace(
                'name="test_create_garden_validates_and_persists" time="0.300" />',
                'name="test_create_garden_validates_and_persists" time="0.300"><failure message="500"/></testcase>',
            ),
            encoding="utf-8",
        )

        checks = tr.build_grounding(tr.load_evidence(pre, post))[0]["code_checks"]

        self.assertEqual([(c["severity"], c["area"]) for c in checks], [("high", "post_commit"), ("high", "post_commit"), ("medium", "post_commit")])
        self.assertIn("event = 'pull_request'", checks[0]["evidence"])
        self.assertIn("failures = 1", checks[1]["evidence"])
        self.assertIn("test_create_garden_validates_and_persists", checks[1]["evidence"])
        self.assertIn("tested_sha ffffffffffff differs", checks[2]["evidence"])

    def test_each_endpoint_function_needs_a_test_and_two_functions_are_required(self):
        pre, post = self.evidence_copy()
        rewrite_run_json(post / "vgarden-sample", endpoint_functions={
            "routes.create_garden": "POST /gardens", "routes.delete_garden": "DELETE /gardens/<id>", "routes.garden_snapshot": "GET",
        })

        checks = tr.build_grounding(tr.load_evidence(pre, post))[0]["code_checks"]

        self.assertEqual([(c["severity"], c["area"]) for c in checks], [("high", "post_commit"), ("medium", "post_commit")])
        self.assertIn("names 3 endpoint function(s)", checks[0]["evidence"])
        self.assertIn("no endpoint test name mentions 'delete_garden'", checks[1]["evidence"])

    def test_missing_files_and_links_are_flagged(self):
        pre, post = self.evidence_copy()
        folder = post / "vgarden-sample"
        (folder / "regressions.xml").unlink()
        (folder / "README.md").unlink()
        rewrite_run_json(folder, run_url="run 1", workflow_file=".github/workflows/nope.yml")

        checks = tr.build_grounding(tr.load_evidence(pre, post))[0]["code_checks"]

        self.assertEqual([(c["severity"], c["evidence"][:14]) for c in checks], [
            ("medium", "regressions.xm"), ("medium", "run_url = 'run"), ("medium", "workflow_file "), ("low", "no README.md d"),
        ])

    def test_students_with_evidence_on_one_side_only_are_coverage_findings(self):
        pre, post = self.evidence_copy()
        shutil.copytree(post / "vgarden-sample", post / "health-other")
        (pre / "almanac-third.md").write_text("# Pre-commit security testing report — almanac (Third)\n", encoding="utf-8")

        checks = tr.build_grounding(tr.load_evidence(pre, post))[0]["code_checks"]

        coverage = [(c["severity"], c["subject"], c["evidence"][:24]) for c in checks if c["area"] == "coverage"]
        self.assertEqual(coverage, [
            ("medium", "almanac-third", "pre-commit report presen"), ("medium", "health-other", "post-commit evidence pre"),
        ])
        # the almanac page has no check rows at all: four missing required checks
        self.assertEqual(sum(1 for c in checks if c["subject"] == "almanac-third" and c["area"] == "pre_commit"), 4)

    def test_a_service_mismatch_between_the_two_sides_is_low(self):
        pre, post = self.evidence_copy()
        rewrite_run_json(post / "vgarden-sample", service="health")
        self.assertEqual(checks_for(pre, post), [("low", "consistency", "vgarden-sample")])


# --------------------------------------------------------------------------- #
# Refusal, validation and normalisation                                       #
# --------------------------------------------------------------------------- #


class NormaliseTests(TempCase):
    def test_refuses_without_any_report(self):
        model = FakeModel(pass_draft())
        reviewer = FakeReviewer()

        decision, result = self.run_loop(self.tmp_path / "none", self.tmp_path / "none2", model, reviewer)

        self.assertEqual((model.calls, reviewer.drafts), ([], []))
        self.assertEqual((decision["decision"], decision["students_reviewed"]), ("insufficient_evidence", 0))
        self.assertEqual(decision["findings"][0]["area"], "coverage")
        self.assertIn("no pre-commit reports", decision["findings"][0]["evidence"])
        self.assertEqual(result.verdict, "approved")
        self.assertEqual(tr.validate(decision), [])

    def test_one_side_present_is_reviewed_not_refused(self):
        pre, _ = self.evidence_copy()
        grounding, _ = tr.build_grounding(tr.load_evidence(pre, self.tmp_path / "no-post"))
        self.assertEqual(grounding["evidence_gaps"], [])
        self.assertIsNone(tr.refusal(grounding))
        self.assertEqual([(c["severity"], c["area"]) for c in grounding["code_checks"]], [("medium", "coverage")])

    def test_validate_rejects_shapes_outside_the_schema(self):
        cases = [
            (pass_draft(decision="approve"), "decision must be one of"),
            (pass_draft(students_reviewed=-1), "students_reviewed must be a non-negative integer"),
            (pass_draft(findings=[finding(area="ci")]), "area must be one of"),
            (pass_draft(findings=[finding(subject=None)]), "subject must be a string"),
            (pass_draft(findings=[finding(recommendation=" ")]), "recommendation must be a non-empty string"),
        ]
        for bad, message in cases:
            with self.subTest(message=message):
                problems = tr.validate(bad)
                self.assertTrue(any(message in problem for problem in problems), problems)

    def test_normalise_adds_omitted_code_findings_drops_unknown_subjects_and_fixes_the_decision(self):
        pre, post = self.evidence_copy()
        (post / "vgarden-sample" / "regressions.xml").unlink()
        grounding, _ = tr.build_grounding(tr.load_evidence(pre, post))
        corrections: list[str] = []

        decision = tr.normalise(pass_draft(students_reviewed=4, findings=[finding(subject="nobody", evidence="ghost")]), grounding, corrections)

        self.assertEqual((decision["decision"], decision["students_reviewed"]), ("pass_with_findings", 1))
        self.assertEqual([(f["severity"], f["area"], f["subject"]) for f in decision["findings"]], [("medium", "post_commit", "vgarden-sample")])
        self.assertTrue(any("dropped finding 'ghost'" in note for note in corrections))
        self.assertIn("added the missing medium finding post_commit for vgarden-sample", corrections)
        self.assertIn("pass is inconsistent with the findings -> pass_with_findings", corrections)
        self.assertIn("students_reviewed corrected to 1 from the grounding", corrections)
        self.assertTrue(decision["summary"].startswith("1 finding(s) in the model's draft were not confirmed"))
        self.assertIn("Corrected in code to pass_with_findings: regressions.xml", decision["summary"])

    def test_normalise_keeps_the_models_wording_when_it_reported_the_code_finding(self):
        pre, post = self.evidence_copy()
        (post / "vgarden-sample" / "README.md").unlink()
        grounding, _ = tr.build_grounding(tr.load_evidence(pre, post))
        corrections: list[str] = []
        raw = pass_draft(findings=[finding(severity="low", evidence="README.md missing from the folder")])

        decision = tr.normalise(raw, grounding, corrections)

        self.assertEqual(decision["findings"], [finding(severity="low", evidence="README.md missing from the folder")])
        self.assertEqual(decision["decision"], "pass")  # a low finding is informational
        self.assertEqual(corrections, [])

    def test_positive_observations_are_not_findings(self):
        grounding, _ = tr.build_grounding(tr.load_evidence(PRE, POST))
        corrections: list[str] = []
        raw = pass_draft(decision="pass_with_findings", findings=[
            finding(area="pre_commit", severity="low", evidence="Ruff security rules passed"),
            finding(area="post_commit", severity="low", evidence="Regression tests passed"),
        ])

        decision = tr.normalise(raw, grounding, corrections)

        self.assertEqual((decision["findings"], decision["decision"]), ([], "pass"))
        self.assertEqual(sum(1 for note in corrections if "check holds for vgarden-sample" in note), 2)
        self.assertTrue(decision["summary"].startswith("2 finding(s) in the model's draft were not confirmed"))


# --------------------------------------------------------------------------- #
# The loop and the runner                                                     #
# --------------------------------------------------------------------------- #


class LoopAndRunnerTests(TempCase):
    def test_the_fixture_passes_in_one_iteration_and_logs_every_phase(self):
        model = FakeModel(pass_draft())
        reviewer = FakeReviewer("approved")

        decision, result = self.run_loop(PRE, POST, model, reviewer)

        self.assertEqual((decision["decision"], result.verdict, result.iterations), ("pass", "approved", 1))
        self.assertEqual(model.calls[0][0], tr.PROMPT_ACT)
        self.assertEqual(model.calls[0][1]["task"], tr.QUESTION)
        self.assertEqual(reviewer.drafts, [decision])
        lines = (self.tmp_path / "logs" / "testing.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual([json.loads(line)["phase"] for line in lines], ["plan", "act", "observe", "adapt"])
        self.assertEqual(json.loads(lines[0])["endpoint_tests"], 2)
        self.assertTrue(Path(result.transcript_path).name.startswith("testing-"))

    def test_reviewer_feedback_is_threaded_into_the_next_draft(self):
        model = FakeModel(pass_draft(summary="first"), pass_draft(summary="second"))

        decision, result = self.run_loop(PRE, POST, model, FakeReviewer("revise", "approved"))

        self.assertEqual((result.iterations, decision["summary"]), (2, "second"))
        self.assertIn("quote the JUnit counts", model.calls[1][1]["reviewer_feedback"])

    def test_run_writes_the_validation_log_next_to_the_evidence(self):
        args = review.build_parser().parse_args(
            ["--mode", "testing", "--pre-commit-dir", str(PRE), "--post-commit-dir", str(POST),
             "--log-dir", str(self.tmp_path / "logs"), "--copy-dir", str(self.tmp_path / "copies"), "--model", "fake", "--review-model", ""]
        )

        summary = tr.run(args, drafter=tr.TestingDrafter(call_model=FakeModel(pass_draft())), reviewer=FakeReviewer())

        self.assertEqual((summary["mode"], summary["decision"]["decision"]), ("testing", "pass"))
        self.assertIsNone(summary["models"]["reviewer"])
        self.assertEqual(summary["loop"]["iterations"], 1)
        log = Path(summary["validation_log"]["markdown"]).read_text(encoding="utf-8")
        for heading in ("# Testing Report Review — validation log", "## Decision", "## Findings", "## Testing recommendations",
                        "## Pre-commit security reports reviewed", "## Post-commit CI/CD reports reviewed",
                        "## Checks computed in code", "## Code corrections applied to the final draft", "## Loop trace", "## Human confirmation"):
            self.assertIn(heading, log)
        self.assertIn("| vgarden-sample | vgarden | Sample Student |", log)
        self.assertIn("`routes.create_garden` POST /gardens", log)
        self.assertIn("2 tests, 0 failed, 0 errors", log)
        self.assertTrue((self.tmp_path / "copies" / "testing-latest-review.json").is_file())
        self.assertEqual(review.EXIT_CODES[summary["decision"]["decision"]], 0)

    def test_modes_are_registered_and_the_defaults_point_at_the_evidence_folders(self):
        self.assertEqual(set(review.MODES), {"multi-agent", "testing"})
        args = review.build_parser().parse_args(["--mode", "testing"])
        self.assertEqual(Path(args.pre_commit_dir), common.EVIDENCE_ROOT / "pre-commit")
        self.assertEqual(Path(args.post_commit_dir), common.EVIDENCE_ROOT / "post-commit")
        self.assertEqual(Path(args.evidence_dir), common.EVIDENCE_ROOT)
        self.assertEqual(common.DEFAULT_COPY_DIR, common.EVIDENCE_ROOT / "agentic-review")

    def test_structured_drafter_requests_the_pinned_schema_at_temperature_zero(self):
        seen = {}

        def fake_post(base_url, path, payload, timeout):
            seen.update(payload)
            return {"message": {"content": json.dumps(pass_draft())}}

        original_post, original_ensure = ai_loop._ollama_post, ai_loop.ensure_model
        ai_loop._ollama_post = fake_post
        ai_loop.ensure_model = lambda *a, **k: None
        self.addCleanup(setattr, ai_loop, "_ollama_post", original_post)
        self.addCleanup(setattr, ai_loop, "ensure_model", original_ensure)
        drafter = tr.TestingDrafter(model="fake")
        grounding, _ = tr.build_grounding(tr.load_evidence(PRE, POST))

        draft = json.loads(drafter.draft("q", grounding))

        self.assertEqual(draft["decision"], "pass")
        self.assertEqual(seen["format"], tr.SCHEMA)
        self.assertEqual((seen["options"]["temperature"], seen["options"]["num_ctx"]), (0, 8192))
        self.assertEqual(seen["messages"][0]["content"], tr.PROMPT_ACT)
        self.assertIn("code_checks", seen["messages"][1]["content"])


if __name__ == "__main__":
    unittest.main()

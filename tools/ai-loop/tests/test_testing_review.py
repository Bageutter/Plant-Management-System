"""Unit tests for the Testing Report Review mode (tools/ai-loop/testing_review.py),
driven with a fake proposer model and a scripted reviewer. No Ollama, no network.

Run from the repository root:
    python -m pytest -q tools/ai-loop/tests
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "shared"))
sys.path.insert(0, str(HERE.parent))
import ai_loop  # noqa: E402
import review_common as common  # noqa: E402
import testing_review as tr  # noqa: E402

_SPEC = importlib.util.spec_from_file_location("ai_loop_review", HERE.parent / "review.py")
review = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(review)

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


def evidence_copy(tmp_path: Path) -> tuple[Path, Path]:
    """A writable copy of the fixture folders."""
    pre, post = tmp_path / "pre-commit", tmp_path / "post-commit"
    shutil.copytree(PRE, pre)
    shutil.copytree(POST, post)
    return pre, post


def checks_for(pre: Path, post: Path) -> list[tuple[str, str, str]]:
    grounding, _ = tr.build_grounding(tr.load_evidence(pre, post))
    return [(c["severity"], c["area"], c["subject"]) for c in grounding["code_checks"]]


def run_loop(pre, post, model, reviewer, tmp_path, **kwargs):
    return tr.review(tr.load_evidence(pre, post), tr.TestingDrafter(call_model=model), reviewer, str(tmp_path / "logs"), **kwargs)


# --------------------------------------------------------------------------- #
# Loading and parsing                                                         #
# --------------------------------------------------------------------------- #


def test_parses_the_report_py_page():
    reports = tr.load_pre_commit_reports(PRE)

    assert len(reports) == 1
    report = reports[0]
    assert report["stem"] == "vgarden-sample" and report["service"] == "vgarden" and report["owner"] == "Sample Student"
    assert report["generated"] == "2026-10-21 08:00 UTC"
    assert set(report["checks"]) == set(tr.REQUIRED_CHECKS)
    assert report["checks"]["ruff"] == {
        "result": "PASS", "run_at": "2026-10-21 07:58", "commit": "0a31150520", "branch": "sample/branch",
        "scope": "3 file(s)", "findings": "no security findings",
    }
    assert report["checks"]["tests"]["findings"] == "41 passed in 12.00s"
    assert report["history_runs"] == 5 and report["history_failed_runs"] == 1


def test_the_readme_is_not_a_report(tmp_path):
    pre, _ = evidence_copy(tmp_path)
    (pre / "README.md").write_text("# index\n", encoding="utf-8")
    assert [r["stem"] for r in tr.load_pre_commit_reports(pre)] == ["vgarden-sample"]
    assert tr.load_pre_commit_reports(tmp_path / "missing") == []


def test_parses_the_ci_artifact_folder():
    runs = tr.load_post_commit_runs(POST)

    assert len(runs) == 1
    run = runs[0]
    assert run["stem"] == "vgarden-sample" and run["event"] == "push" and run["workflow"] == "Virtual Garden (Sample)"
    assert run["workflow_file"] == ".github/workflows/vgarden.yml" and run["workflow_file_in_repo"] is True
    assert run["source_sha"] == run["tested_sha"] == "0a31150520c0"
    assert run["endpoint_functions"] == {"routes.create_garden": "POST /gardens", "routes.garden_snapshot": "GET /gardens/<id>/snapshot"}
    assert run["endpoint_tests"]["tests"] == 2 and run["endpoint_tests"]["failures"] == 0
    assert [c["name"] for c in run["endpoint_tests"]["cases"]] == [
        "test_create_garden_validates_and_persists", "test_garden_snapshot_is_owner_scoped_and_read_only",
    ]
    assert run["regression_tests"] == {"tests": 3, "failures": 0, "errors": 0, "skipped": 1, "failed_cases": ["test_container_crud"]}
    assert run["readme_present"] and run["run_json_present"]


def test_junit_parsing_reports_failures_and_unreadable_files(tmp_path):
    xml = tmp_path / "x.xml"
    xml.write_text(
        '<testsuite tests="2" failures="1" errors="0" skipped="0"><testcase name="ok"/>'
        '<testcase name="bad"><failure message="boom"/></testcase></testsuite>',
        encoding="utf-8",
    )
    parsed = tr.parse_junit(xml)
    assert parsed["failures"] == 1 and [c["outcome"] for c in parsed["cases"]] == ["passed", "failure"]

    xml.write_text("<testsuite", encoding="utf-8")
    assert tr.parse_junit(xml)["parse_error"] is True
    assert tr.parse_junit(tmp_path / "none.xml") is None


# --------------------------------------------------------------------------- #
# PLAN: the code checks                                                       #
# --------------------------------------------------------------------------- #


def test_the_fixture_evidence_passes_every_code_check():
    grounding, plan = tr.build_grounding(tr.load_evidence(PRE, POST))

    assert grounding["code_checks"] == [] and grounding["evidence_gaps"] == []
    assert plan == {
        "pre_commit_reports": 1, "post_commit_runs": 1, "students": 1, "endpoint_tests": 2, "regression_tests": 3,
        "code_findings": "high=0 medium=0 low=0", "evidence_gaps": 0,
    }
    assert grounding["students"] == [{"stem": "vgarden-sample", "has_pre_commit": True, "has_post_commit": True}]
    assert set(grounding["required_pre_commit_checks"]) == {"ruff", "secrets", "audit", "tests"}


def test_a_failed_or_missing_required_scan_is_high(tmp_path):
    pre, post = evidence_copy(tmp_path)
    page = pre / "vgarden-sample.md"
    text = page.read_text(encoding="utf-8")
    text = text.replace("| detect-secrets (`detect-secrets-hook --baseline .secrets.baseline`) | PASS |",
                        "| detect-secrets (`detect-secrets-hook --baseline .secrets.baseline`) | FAIL |")
    text = "\n".join(line for line in text.splitlines() if not line.startswith("| pip-audit"))
    page.write_text(text, encoding="utf-8")

    checks = tr.build_grounding(tr.load_evidence(pre, post))[0]["code_checks"]

    assert [(c["severity"], c["area"]) for c in checks] == [("high", "pre_commit"), ("high", "pre_commit")]
    assert "detect-secrets' = FAIL" in checks[0]["evidence"]
    assert "pip-audit dependency vulnerabilities' not run" in checks[1]["evidence"]


def test_a_non_push_run_and_red_tests_are_high(tmp_path):
    pre, post = evidence_copy(tmp_path)
    run_path = post / "vgarden-sample" / "run.json"
    run = json.loads(run_path.read_text(encoding="utf-8"))
    run["event"] = "pull_request"
    run["tested_sha"] = "ffffffffffffffffffffffffffffffffffffffff"
    run_path.write_text(json.dumps(run), encoding="utf-8")
    endpoints = post / "vgarden-sample" / "endpoints.xml"
    endpoints.write_text(
        endpoints.read_text(encoding="utf-8").replace('failures="0"', 'failures="1"').replace(
            'name="test_create_garden_validates_and_persists" time="0.300" />',
            'name="test_create_garden_validates_and_persists" time="0.300"><failure message="500"/></testcase>',
        ),
        encoding="utf-8",
    )

    checks = tr.build_grounding(tr.load_evidence(pre, post))[0]["code_checks"]

    assert [(c["severity"], c["area"]) for c in checks] == [("high", "post_commit"), ("high", "post_commit"), ("medium", "post_commit")]
    assert "event = 'pull_request'" in checks[0]["evidence"]
    assert "failures = 1" in checks[1]["evidence"] and "test_create_garden_validates_and_persists" in checks[1]["evidence"]
    assert "tested_sha ffffffffffff differs" in checks[2]["evidence"]


def test_each_endpoint_function_needs_a_test_and_two_functions_are_required(tmp_path):
    pre, post = evidence_copy(tmp_path)
    run_path = post / "vgarden-sample" / "run.json"
    run = json.loads(run_path.read_text(encoding="utf-8"))
    run["endpoint_functions"] = {"routes.create_garden": "POST /gardens", "routes.delete_garden": "DELETE /gardens/<id>",
                                 "routes.garden_snapshot": "GET"}
    run_path.write_text(json.dumps(run), encoding="utf-8")

    checks = tr.build_grounding(tr.load_evidence(pre, post))[0]["code_checks"]

    assert [(c["severity"], c["area"]) for c in checks] == [("high", "post_commit"), ("medium", "post_commit")]
    assert "names 3 endpoint function(s)" in checks[0]["evidence"]
    assert "no endpoint test name mentions 'delete_garden'" in checks[1]["evidence"]


def test_missing_files_and_links_are_flagged(tmp_path):
    pre, post = evidence_copy(tmp_path)
    folder = post / "vgarden-sample"
    (folder / "regressions.xml").unlink()
    (folder / "README.md").unlink()
    run = json.loads((folder / "run.json").read_text(encoding="utf-8"))
    run["run_url"] = "run 1"
    run["workflow_file"] = ".github/workflows/nope.yml"
    (folder / "run.json").write_text(json.dumps(run), encoding="utf-8")

    checks = tr.build_grounding(tr.load_evidence(pre, post))[0]["code_checks"]

    assert [(c["severity"], c["evidence"][:14]) for c in checks] == [
        ("medium", "regressions.xm"), ("medium", "run_url = 'run"), ("medium", "workflow_file "), ("low", "no README.md d"),
    ]


def test_students_with_evidence_on_one_side_only_are_coverage_findings(tmp_path):
    pre, post = evidence_copy(tmp_path)
    shutil.copytree(post / "vgarden-sample", post / "health-other")
    (pre / "almanac-third.md").write_text("# Pre-commit security testing report — almanac (Third)\n", encoding="utf-8")

    checks = tr.build_grounding(tr.load_evidence(pre, post))[0]["code_checks"]

    coverage = [(c["severity"], c["subject"], c["evidence"][:24]) for c in checks if c["area"] == "coverage"]
    assert coverage == [
        ("medium", "almanac-third", "pre-commit report presen"), ("medium", "health-other", "post-commit evidence pre"),
    ]
    # the almanac page has no check rows at all: four missing required checks
    assert sum(1 for c in checks if c["subject"] == "almanac-third" and c["area"] == "pre_commit") == 4


def test_a_service_mismatch_between_the_two_sides_is_low(tmp_path):
    pre, post = evidence_copy(tmp_path)
    run_path = post / "vgarden-sample" / "run.json"
    run = json.loads(run_path.read_text(encoding="utf-8"))
    run["service"] = "health"
    run_path.write_text(json.dumps(run), encoding="utf-8")

    assert checks_for(pre, post) == [("low", "consistency", "vgarden-sample")]


# --------------------------------------------------------------------------- #
# Refusal, validation and normalisation                                       #
# --------------------------------------------------------------------------- #


def test_refuses_without_any_report(tmp_path):
    model = FakeModel(pass_draft())
    reviewer = FakeReviewer()

    decision, result = run_loop(tmp_path / "none", tmp_path / "none2", model, reviewer, tmp_path)

    assert model.calls == [] and reviewer.drafts == []
    assert decision["decision"] == "insufficient_evidence" and decision["students_reviewed"] == 0
    assert decision["findings"][0]["area"] == "coverage" and "no pre-commit reports" in decision["findings"][0]["evidence"]
    assert result.verdict == "approved" and tr.validate(decision) == []


def test_one_side_present_is_reviewed_not_refused(tmp_path):
    pre, _ = evidence_copy(tmp_path)
    grounding, _ = tr.build_grounding(tr.load_evidence(pre, tmp_path / "no-post"))
    assert grounding["evidence_gaps"] == [] and tr.refusal(grounding) is None
    assert [(c["severity"], c["area"]) for c in grounding["code_checks"]] == [("medium", "coverage")]


@pytest.mark.parametrize(
    "bad, message",
    [
        (pass_draft(decision="approve"), "decision must be one of"),
        (pass_draft(students_reviewed=-1), "students_reviewed must be a non-negative integer"),
        (pass_draft(findings=[finding(area="ci")]), "area must be one of"),
        (pass_draft(findings=[finding(subject=None)]), "subject must be a string"),
        (pass_draft(findings=[finding(recommendation=" ")]), "recommendation must be a non-empty string"),
    ],
)
def test_validate_rejects_shapes_outside_the_schema(bad, message):
    assert any(message in problem for problem in tr.validate(bad)), tr.validate(bad)


def test_normalise_adds_omitted_code_findings_drops_unknown_subjects_and_fixes_the_decision(tmp_path):
    pre, post = evidence_copy(tmp_path)
    (post / "vgarden-sample" / "regressions.xml").unlink()
    grounding, _ = tr.build_grounding(tr.load_evidence(pre, post))
    corrections: list[str] = []

    decision = tr.normalise(pass_draft(students_reviewed=4, findings=[finding(subject="nobody", evidence="ghost")]), grounding, corrections)

    assert decision["decision"] == "pass_with_findings" and decision["students_reviewed"] == 1
    assert [(f["severity"], f["area"], f["subject"]) for f in decision["findings"]] == [("medium", "post_commit", "vgarden-sample")]
    assert any("dropped finding 'ghost'" in note for note in corrections)
    assert "added the missing medium finding post_commit for vgarden-sample" in corrections
    assert "pass is inconsistent with the findings -> pass_with_findings" in corrections
    assert "students_reviewed corrected to 1 from the grounding" in corrections
    assert decision["summary"].startswith("1 finding(s) in the model's draft were not confirmed")
    assert "Corrected in code to pass_with_findings: regressions.xml" in decision["summary"]


def test_normalise_keeps_the_models_wording_when_it_reported_the_code_finding(tmp_path):
    pre, post = evidence_copy(tmp_path)
    (post / "vgarden-sample" / "README.md").unlink()
    grounding, _ = tr.build_grounding(tr.load_evidence(pre, post))
    corrections: list[str] = []
    raw = pass_draft(findings=[finding(severity="low", evidence="README.md missing from the folder")])

    decision = tr.normalise(raw, grounding, corrections)

    assert decision["findings"] == [finding(severity="low", evidence="README.md missing from the folder")]
    assert decision["decision"] == "pass"  # a low finding is informational
    assert corrections == []


def test_positive_observations_are_not_findings():
    grounding, _ = tr.build_grounding(tr.load_evidence(PRE, POST))
    corrections: list[str] = []
    raw = pass_draft(decision="pass_with_findings", findings=[
        finding(area="pre_commit", severity="low", evidence="Ruff security rules passed"),
        finding(area="post_commit", severity="low", evidence="Regression tests passed"),
    ])

    decision = tr.normalise(raw, grounding, corrections)

    assert decision["findings"] == [] and decision["decision"] == "pass"
    assert sum(1 for note in corrections if "check holds for vgarden-sample" in note) == 2
    assert decision["summary"].startswith("2 finding(s) in the model's draft were not confirmed")


# --------------------------------------------------------------------------- #
# The loop and the runner                                                     #
# --------------------------------------------------------------------------- #


def test_the_fixture_passes_in_one_iteration_and_logs_every_phase(tmp_path):
    model = FakeModel(pass_draft())
    reviewer = FakeReviewer("approved")

    decision, result = run_loop(PRE, POST, model, reviewer, tmp_path)

    assert decision["decision"] == "pass" and result.verdict == "approved" and result.iterations == 1
    assert model.calls[0][0] == tr.PROMPT_ACT and model.calls[0][1]["task"] == tr.QUESTION
    assert reviewer.drafts == [decision]
    lines = (tmp_path / "logs" / "testing.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["phase"] for line in lines] == ["plan", "act", "observe", "adapt"]
    assert json.loads(lines[0])["endpoint_tests"] == 2
    assert Path(result.transcript_path).name.startswith("testing-")


def test_reviewer_feedback_is_threaded_into_the_next_draft(tmp_path):
    model = FakeModel(pass_draft(summary="first"), pass_draft(summary="second"))

    decision, result = run_loop(PRE, POST, model, FakeReviewer("revise", "approved"), tmp_path)

    assert result.iterations == 2 and decision["summary"] == "second"
    assert "quote the JUnit counts" in model.calls[1][1]["reviewer_feedback"]


def test_run_writes_the_validation_log_next_to_the_evidence(tmp_path):
    args = review.build_parser().parse_args(
        ["--mode", "testing", "--pre-commit-dir", str(PRE), "--post-commit-dir", str(POST),
         "--log-dir", str(tmp_path / "logs"), "--copy-dir", str(tmp_path / "copies"), "--model", "fake", "--review-model", ""]
    )

    summary = tr.run(args, drafter=tr.TestingDrafter(call_model=FakeModel(pass_draft())), reviewer=FakeReviewer())

    assert summary["mode"] == "testing" and summary["decision"]["decision"] == "pass"
    assert summary["models"]["reviewer"] is None and summary["loop"]["iterations"] == 1
    log = Path(summary["validation_log"]["markdown"]).read_text(encoding="utf-8")
    for heading in ("# Testing Report Review — validation log", "## Decision", "## Findings", "## Testing recommendations",
                    "## Pre-commit security reports reviewed", "## Post-commit CI/CD reports reviewed",
                    "## Checks computed in code", "## Code corrections applied to the final draft", "## Loop trace", "## Human confirmation"):
        assert heading in log
    assert "| vgarden-sample | vgarden | Sample Student |" in log
    assert "`routes.create_garden` POST /gardens" in log and "2 tests, 0 failed, 0 errors" in log
    assert (tmp_path / "copies" / "testing-latest-review.json").is_file()
    assert review.EXIT_CODES[summary["decision"]["decision"]] == 0


def test_modes_are_registered_and_the_defaults_point_at_the_evidence_folders():
    assert set(review.MODES) == {"multi-agent", "testing", "cloud-deployment"}
    args = review.build_parser().parse_args(["--mode", "testing"])
    assert Path(args.pre_commit_dir) == common.EVIDENCE_ROOT / "pre-commit"
    assert Path(args.post_commit_dir) == common.EVIDENCE_ROOT / "post-commit"
    assert Path(args.evidence_dir) == common.EVIDENCE_ROOT
    assert common.DEFAULT_COPY_DIR == common.EVIDENCE_ROOT / "agentic-review"


def test_structured_drafter_requests_the_pinned_schema_at_temperature_zero(monkeypatch):
    seen = {}

    def fake_post(base_url, path, payload, timeout):
        seen.update(payload)
        return {"message": {"content": json.dumps(pass_draft())}}

    monkeypatch.setattr(ai_loop, "_ollama_post", fake_post)
    monkeypatch.setattr(ai_loop, "ensure_model", lambda *a, **k: None)
    drafter = tr.TestingDrafter(model="fake")
    grounding, _ = tr.build_grounding(tr.load_evidence(PRE, POST))

    draft = json.loads(drafter.draft("q", grounding))

    assert draft["decision"] == "pass"
    assert seen["format"] == tr.SCHEMA and seen["options"]["temperature"] == 0 and seen["options"]["num_ctx"] == 8192
    assert seen["messages"][0]["content"] == tr.PROMPT_ACT and "code_checks" in seen["messages"][1]["content"]

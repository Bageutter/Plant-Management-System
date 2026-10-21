"""Unit tests for the Cloud Deployment Report Review mode (shared/ai_loop.py +
tools/ai-loop/review.py), driven with a fake proposer model and a scripted
reviewer. No Ollama, no network.

Run from the repository root:
    python -m pytest -q tools/ai-loop/tests
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "shared"))
import ai_loop  # noqa: E402

# review.py lives in a hyphenated folder, so load it by path like tools/ai-dev's tests do.
_SPEC = importlib.util.spec_from_file_location("ai_loop_review", HERE.parent / "review.py")
review = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(review)

FIXTURE = HERE / "fixtures" / "cloud-deployment-sample.json"


def sample_report() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


class FakeModel:
    """Stands in for the Ollama proposer: returns the scripted JSON objects in turn."""

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
        return {"verdict": "revise", "issues": ["evidence not in grounding"], "guidance": "cite a grounding value"}


def approve_draft(**overrides) -> dict:
    draft = {
        "decision": "approve",
        "baseline_compliant": True,
        "findings": [],
        "release_recommendation": "Approve: smoke test passed and the required baseline holds.",
    }
    draft.update(overrides)
    return draft


def drafter_with(model: FakeModel) -> ai_loop.CloudDeploymentDrafter:
    return ai_loop.CloudDeploymentDrafter(call_model=model)


def run_loop(report, model, reviewer, tmp_path, max_iterations=2):
    return ai_loop.review_cloud_deployment(
        report, drafter_with(model), reviewer, str(tmp_path), max_iterations=max_iterations
    )


# --------------------------------------------------------------------------- #
# Grounding (PLAN)                                                            #
# --------------------------------------------------------------------------- #


def test_grounding_selects_the_reviewable_facts_only():
    grounding, plan = ai_loop.build_cloud_deployment_grounding(sample_report())

    assert grounding["deployment"]["commit"].startswith("0a31150")
    assert grounding["deployment"]["workflow_run_url"].startswith("https://")
    assert set(grounding["endpoints"]["public_urls"]) == {"auth", "vgarden", "almanac", "health"}
    assert grounding["cloud_baseline"] == {flag: False for flag in ai_loop.CLOUD_BASELINE_FLAGS}
    assert grounding["smoke_test"] == {"result": "pass"}
    assert [app["name"] for app in grounding["container_apps"]][0] == "pms-proxy"
    assert set(grounding["container_apps"][0]) == {
        "name", "external", "allowInsecure", "image", "revision", "status", "minReplicas", "maxReplicas",
    }
    assert grounding["postgres"][0]["publicNetworkAccess"] == "Disabled"
    assert grounding["key_vaults"][0] == {"name": "pms-kv-release2", "rbac": True, "softDelete": True}
    assert grounding["storage_accounts"][0]["blobPublicAccess"] is False
    assert len(grounding["security_controls"]) == 8
    assert grounding["evidence_gaps"] == []
    # bulky, non-reviewable sections stay out of the model's context
    assert "resources" not in grounding and "platform_outputs" not in grounding
    assert "internal_fqdns" not in grounding["endpoints"]
    assert plan["smoke_result"] == "pass" and plan["evidence_gaps"] == 0 and plan["container_apps"] == 5


def test_grounding_rejects_a_non_object_report():
    with pytest.raises(ValueError):
        ai_loop.build_cloud_deployment_grounding(["not", "a", "report"])


# --------------------------------------------------------------------------- #
# Refusals: insufficient evidence, decided in code without a model call       #
# --------------------------------------------------------------------------- #


def test_refuses_when_the_smoke_result_is_missing(tmp_path):
    report = sample_report()
    report["smoke_test"] = {"result": "unknown"}
    model = FakeModel(approve_draft())
    reviewer = FakeReviewer("approved")

    decision, result = run_loop(report, model, reviewer, tmp_path)

    assert model.calls == []  # nothing to guess from -> the proposer is never asked
    assert decision["decision"] == "insufficient_evidence"
    assert decision["baseline_compliant"] is False
    assert [f["area"] for f in decision["findings"]] == ["smoke_test"]
    assert decision["findings"][0]["severity"] == "high"
    assert "smoke_test.result" in decision["findings"][0]["evidence"]
    assert decision["release_recommendation"].startswith("Insufficient evidence")
    # OBSERVE is deterministic for a refusal: approved on the first pass, model reviewer unused
    assert result.verdict == "approved" and result.iterations == 1
    assert reviewer.drafts == []
    observe = next(e for e in result.trace if e["phase"] == "observe")
    assert observe["verdict"] == "approved" and "reviewer model not consulted" in observe["issues"]


def test_refuses_when_the_baseline_flags_are_missing(tmp_path):
    report = sample_report()
    del report["cloud_baseline"]
    model = FakeModel(approve_draft())

    decision, _ = run_loop(report, model, FakeReviewer(), tmp_path)

    assert model.calls == []
    assert decision["decision"] == "insufficient_evidence"
    assert [f["area"] for f in decision["findings"]] == ["cloud_baseline"]
    assert "cloud_baseline flags missing" in decision["findings"][0]["evidence"]
    for flag in ai_loop.CLOUD_BASELINE_FLAGS:
        assert flag in decision["findings"][0]["evidence"]


def test_refusal_is_checked_deterministically_even_without_a_review_model(tmp_path):
    report = sample_report()
    report["smoke_test"] = {"result": None}

    decision, result = run_loop(report, FakeModel(approve_draft()), None, tmp_path)

    assert decision["decision"] == "insufficient_evidence"
    assert result.verdict == "approved"  # not the single-shot fallback
    assert [e["phase"] for e in result.trace] == ["plan", "act", "observe", "adapt"]


def test_a_draft_that_is_not_the_refusal_is_sent_back_when_evidence_is_missing():
    report = sample_report()
    report["smoke_test"] = {}
    grounding, _ = ai_loop.build_cloud_deployment_grounding(report)
    reviewer = ai_loop.CloudDeploymentReviewer(None)

    verdict = reviewer.review("q", grounding, json.dumps(approve_draft()))

    assert verdict["verdict"] == "revise" and "fixed refusal" in verdict["issues"][0]


def test_reviewer_wrapper_delegates_real_reviews_to_the_model_reviewer():
    grounding, _ = ai_loop.build_cloud_deployment_grounding(sample_report())
    inner = FakeReviewer("revise")

    verdict = ai_loop.CloudDeploymentReviewer(inner).review("q", grounding, json.dumps(approve_draft()))

    assert verdict["verdict"] == "revise" and inner.drafts == [approve_draft()]
    with pytest.raises(ai_loop.LoopError):
        ai_loop.CloudDeploymentReviewer(None).review("q", grounding, json.dumps(approve_draft()))


def test_a_partial_flag_set_names_only_the_missing_flags():
    report = sample_report()
    report["cloud_baseline"] = {"ai_mode_enabled": False, "mcp_enabled": "false"}  # a string is not a flag

    grounding, _ = ai_loop.build_cloud_deployment_grounding(report)

    assert grounding["cloud_baseline"]["ai_mode_enabled"] is False
    assert grounding["cloud_baseline"]["mcp_enabled"] is None
    assert len(grounding["evidence_gaps"]) == 1
    assert "mcp_enabled, rag_enabled, multi_agent_enabled" in grounding["evidence_gaps"][0]


def test_both_gaps_produce_two_refusal_findings():
    report = sample_report()
    report["smoke_test"] = {}
    report["cloud_baseline"] = {}
    grounding, _ = ai_loop.build_cloud_deployment_grounding(report)

    refusal = ai_loop.cloud_deployment_refusal(grounding)

    assert refusal["decision"] == "insufficient_evidence"
    assert [f["area"] for f in refusal["findings"]] == ["smoke_test", "cloud_baseline"]
    assert ai_loop.validate_cloud_decision(refusal) == []


# --------------------------------------------------------------------------- #
# Schema validation and normalisation of the model's output                  #
# --------------------------------------------------------------------------- #


def test_schema_constant_pins_the_enums():
    schema = ai_loop.CLOUD_DECISION_SCHEMA
    assert schema["required"] == ["decision", "baseline_compliant", "findings", "release_recommendation"]
    assert schema["properties"]["decision"]["enum"] == list(ai_loop.CLOUD_DECISIONS)
    finding = schema["properties"]["findings"]["items"]
    assert finding["properties"]["severity"]["enum"] == ["high", "medium", "low"]
    assert finding["properties"]["area"]["enum"] == list(ai_loop.CLOUD_AREAS)
    assert finding["required"] == ["severity", "area", "evidence", "recommendation"]


@pytest.mark.parametrize(
    "bad, message",
    [
        ("not json object", "must be a JSON object"),
        (approve_draft(decision="maybe"), "decision must be one of"),
        (approve_draft(baseline_compliant="yes"), "baseline_compliant must be a boolean"),
        (approve_draft(release_recommendation=""), "release_recommendation must be a non-empty string"),
        (approve_draft(findings={"severity": "high"}), "findings must be a list"),
        (approve_draft(findings=["high"]), "findings[0] must be an object"),
        (
            approve_draft(findings=[{"severity": "urgent", "area": "postgres", "evidence": "x", "recommendation": "y"}]),
            "severity must be high, medium or low",
        ),
        (
            approve_draft(findings=[{"severity": "low", "area": "network", "evidence": "x", "recommendation": "y"}]),
            "area must be one of",
        ),
        (
            approve_draft(findings=[{"severity": "low", "area": "postgres", "evidence": "", "recommendation": "y"}]),
            "evidence must be a non-empty string",
        ),
    ],
)
def test_validate_cloud_decision_rejects_shapes_outside_the_schema(bad, message):
    problems = ai_loop.validate_cloud_decision(bad)
    assert any(message in problem for problem in problems), problems


def test_invalid_model_output_is_a_loop_error_not_a_decision(tmp_path):
    model = FakeModel({"decision": "approve"})  # missing the other required keys

    with pytest.raises(ai_loop.LoopError, match="invalid decision"):
        drafter_with(model).draft("q", ai_loop.build_cloud_deployment_grounding(sample_report())[0])


def test_valid_output_is_normalised_and_clipped():
    grounding, _ = ai_loop.build_cloud_deployment_grounding(sample_report())
    raw = approve_draft(
        decision="approve_with_corrections",
        findings=[
            {
                "severity": "low",
                "area": "container_apps",
                "evidence": "  container_apps[1].minReplicas = 0 \n (scale to zero)  ",
                "recommendation": "x" * 500,
            }
        ],
    )

    decision = ai_loop.normalise_cloud_decision(raw, grounding)

    assert decision["decision"] == "approve_with_corrections"
    assert decision["baseline_compliant"] is True
    assert decision["findings"][0]["evidence"] == "container_apps[1].minReplicas = 0 (scale to zero)"
    assert len(decision["findings"][0]["recommendation"]) == ai_loop.CLOUD_MAX_FIELD_CHARS
    assert ai_loop.validate_cloud_decision(decision) == []


def test_model_may_not_refuse_when_the_evidence_is_complete():
    grounding, _ = ai_loop.build_cloud_deployment_grounding(sample_report())
    decision = ai_loop.normalise_cloud_decision(approve_draft(decision="insufficient_evidence"), grounding)
    assert decision["decision"] == "reject"


# --------------------------------------------------------------------------- #
# Release rules enforced whatever the model said                              #
# --------------------------------------------------------------------------- #


def test_an_enabled_ai_service_is_a_baseline_breach(tmp_path):
    report = sample_report()
    report["cloud_baseline"]["mcp_enabled"] = True
    report["cloud_baseline"]["rag_enabled"] = True
    model = FakeModel(approve_draft())  # the model wrongly approves with no findings
    drafter = drafter_with(model)

    decision, _ = ai_loop.review_cloud_deployment(report, drafter, FakeReviewer(), str(tmp_path))

    assert len(model.calls) == 1
    assert decision["baseline_compliant"] is False
    assert decision["decision"] == "approve_with_corrections"  # never "approve" with a breach
    assert "approve with an enabled baseline switch -> approve_with_corrections" in drafter.last_corrections
    assert "baseline_compliant corrected to False from the grounding flags" in drafter.last_corrections
    # the model's "no further action" prose may not stand under a corrected decision
    assert decision["release_recommendation"].startswith("Corrected in code to approve_with_corrections: ")
    assert "mcp_enabled" in decision["release_recommendation"]
    assert "The model's draft said: Approve:" in decision["release_recommendation"]
    breaches = [f for f in decision["findings"] if f["area"] == "cloud_baseline"]
    assert {f["severity"] for f in breaches} == {"high"}
    assert any("mcp_enabled" in f["evidence"] for f in breaches)
    assert any("rag_enabled" in f["evidence"] for f in breaches)
    # the system prompt itself states the rule the code enforces
    assert "baseline breach" in model.calls[0][0]


def test_a_model_reported_breach_is_kept_not_duplicated():
    report = sample_report()
    report["cloud_baseline"]["ai_mode_enabled"] = True
    grounding, _ = ai_loop.build_cloud_deployment_grounding(report)
    raw = approve_draft(
        decision="reject",
        baseline_compliant=False,
        findings=[
            {
                "severity": "high",
                "area": "cloud_baseline",
                "evidence": "cloud_baseline.ai_mode_enabled = true",
                "recommendation": "Redeploy with AI-Mode off.",
            }
        ],
    )

    decision = ai_loop.normalise_cloud_decision(raw, grounding)

    assert decision["decision"] == "reject"
    assert len(decision["findings"]) == 1
    assert decision["release_recommendation"] == raw["release_recommendation"]


def test_a_finding_that_contradicts_a_disabled_flag_is_dropped_and_recorded(tmp_path):
    """The live qwen2.5vl run claimed every switch was 'Enabled' while the grounding
    had all four false, and still said approve; the code must not pass that on."""
    model = FakeModel(
        approve_draft(
            findings=[
                {
                    "severity": "high",
                    "area": "cloud_baseline",
                    "evidence": "ai_mode_enabled = Enabled",
                    "recommendation": "Disable it.",
                },
                {
                    "severity": "low",
                    "area": "container_apps",
                    "evidence": "container_apps[1].minReplicas = 0",
                    "recommendation": "Consider a warm replica for auth.",
                },
            ]
        )
    )
    drafter = drafter_with(model)

    decision, _ = ai_loop.review_cloud_deployment(
        sample_report(), drafter, FakeReviewer(), str(tmp_path)
    )

    assert decision["decision"] == "approve"
    assert [f["area"] for f in decision["findings"]] == ["container_apps"]
    assert any(note.startswith("dropped finding") and "ai_mode_enabled=false" in note for note in drafter.last_corrections)


def test_approve_with_a_high_finding_becomes_approve_with_corrections():
    grounding, _ = ai_loop.build_cloud_deployment_grounding(sample_report())
    notes: list[str] = []
    raw = approve_draft(
        findings=[
            {
                "severity": "high",
                "area": "postgres",
                "evidence": "postgres[0].backupRetentionDays = 7",
                "recommendation": "Raise retention to 14 days.",
            }
        ]
    )

    decision = ai_loop.normalise_cloud_decision(raw, grounding, notes)

    assert decision["decision"] == "approve_with_corrections"
    assert notes == ["approve with a high finding is inconsistent -> approve_with_corrections"]


def test_corrections_are_recorded_for_the_refusal_and_for_a_clean_draft():
    gap_report = sample_report()
    gap_report["smoke_test"] = {}
    drafter = drafter_with(FakeModel(approve_draft()))

    drafter.draft("q", ai_loop.build_cloud_deployment_grounding(gap_report)[0])
    assert drafter.last_corrections == [
        "evidence gaps -> fixed insufficient_evidence decision, no model call"
    ]

    drafter.draft("q", ai_loop.build_cloud_deployment_grounding(sample_report())[0])
    assert drafter.last_corrections == []


def test_a_failed_smoke_test_rejects(tmp_path):
    report = sample_report()
    report["smoke_test"]["result"] = "FAIL"
    model = FakeModel(approve_draft())

    decision, _ = run_loop(report, model, FakeReviewer(), tmp_path)

    assert decision["decision"] == "reject"
    assert decision["findings"][0] == {
        "severity": "high",
        "area": "smoke_test",
        "evidence": "smoke_test.result = fail",
        "recommendation": "Fix the failing endpoint, redeploy and re-run scripts/deploy/azure-smoke.sh.",
    }
    assert decision["release_recommendation"].startswith("Corrected in code to reject: smoke_test.result = fail")


# --------------------------------------------------------------------------- #
# The loop: feedback threading and the three evidence sinks                   #
# --------------------------------------------------------------------------- #


def test_reviewer_guidance_is_carried_into_the_next_draft(tmp_path):
    model = FakeModel(approve_draft(), approve_draft(release_recommendation="Approve (revised)."))

    decision, result = run_loop(sample_report(), model, FakeReviewer("revise", "approved"), tmp_path)

    assert result.iterations == 2 and result.verdict == "approved"
    assert "reviewer_feedback" not in model.calls[0][1]
    assert "cite a grounding value" in model.calls[1][1]["reviewer_feedback"]
    assert model.calls[1][1]["grounding"]["smoke_test"] == {"result": "pass"}
    assert decision["release_recommendation"] == "Approve (revised)."


def test_no_reviewer_is_a_logged_single_shot_fallback(tmp_path):
    decision, result = run_loop(sample_report(), FakeModel(approve_draft()), None, tmp_path)

    assert decision["decision"] == "approve"
    assert result.verdict == "fallback"
    assert [e["phase"] for e in result.trace] == ["plan", "fallback"]


def test_run_cloud_deployment_writes_all_sinks_and_the_validation_log(tmp_path, caplog):
    import logging

    caplog.set_level(logging.INFO, logger="ai_loop")
    log_dir = tmp_path / "logs"
    copy_dir = tmp_path / "evidence"
    args = argparse.Namespace(
        report=str(FIXTURE), ollama_url="http://localhost:11434", model="fake-proposer",
        review_model="fake-reviewer", max_iterations=2, auto_pull=False, log_dir=log_dir,
        copy_dir=copy_dir, no_copy=False, output=None,
    )

    summary = review.run_cloud_deployment(
        args, drafter=drafter_with(FakeModel(approve_draft())), reviewer=FakeReviewer("approved")
    )

    assert summary["decision"]["decision"] == "approve"
    assert summary["loop"]["verdict"] == "approved"
    assert review.EXIT_CODES[summary["decision"]["decision"]] == 0
    # 1. stdout logger
    assert any("PLAN" in r.message and "smoke_result=pass" in r.message for r in caplog.records)
    assert any("ADAPT" in r.message for r in caplog.records)
    # 2. JSONL, under the mode's own service name
    events = [json.loads(line) for line in (log_dir / "cloud-deployment.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [e["phase"] for e in events] == ["plan", "act", "observe", "adapt"]
    assert all(e["service"] == "cloud-deployment" and e["run_id"] == summary["run_id"] for e in events)
    # 3. markdown transcript
    transcript = Path(summary["loop"]["transcript"])
    assert transcript == log_dir / "reports" / "cloud-deployment" / f"{summary['run_id']}.md"
    assert "## OBSERVE" in transcript.read_text(encoding="utf-8")
    # + the validation log next to the report, stamped like azure_report.py's files
    md = Path(summary["validation_log"]["markdown"])
    assert md == copy_dir / "cloud-deployment-20261020T061542Z-review.md"
    text = md.read_text(encoding="utf-8")
    assert "# Cloud Deployment Report Review — validation log" in text
    assert "| **approve** | yes | pass | 0 |" in text
    assert "## Final human release decision" in text and "- [ ] **Approved**" in text
    assert "## Code corrections applied to the final draft" in text
    assert summary["code_corrections"] == []
    assert "| PLAN |" in text and "| OBSERVE |" in text
    saved = json.loads(Path(summary["validation_log"]["json"]).read_text(encoding="utf-8"))
    assert saved["decision"] == summary["decision"]
    assert (copy_dir / "latest-review.md").read_text(encoding="utf-8") == text


def test_refusal_exit_code_and_log(tmp_path):
    report = sample_report()
    report["smoke_test"] = {}
    report_path = tmp_path / "latest.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    args = argparse.Namespace(
        report=str(report_path), ollama_url="http://localhost:11434", model="fake", review_model="",
        max_iterations=2, auto_pull=False, log_dir=tmp_path / "logs", copy_dir=None, no_copy=False, output=None,
    )

    summary = review.run_cloud_deployment(args, drafter=drafter_with(FakeModel(approve_draft())))

    assert summary["decision"]["decision"] == "insufficient_evidence"
    assert review.EXIT_CODES["insufficient_evidence"] == 2
    log = (tmp_path / "latest-review.md").read_text(encoding="utf-8")  # next to the report by default
    assert "**insufficient_evidence**" in log and "smoke_test.result is missing" in log
    assert summary["code_corrections"] == [
        "evidence gaps -> fixed insufficient_evidence decision, no model call"
    ]
    assert "- evidence gaps -> fixed insufficient_evidence decision, no model call" in log


def test_main_fails_clearly_without_a_report(tmp_path, capsys):
    with pytest.raises(SystemExit) as exit_info:
        review.main(["--mode", "cloud-deployment", "--report", str(tmp_path / "missing.json")])
    assert "No report at" in str(exit_info.value)

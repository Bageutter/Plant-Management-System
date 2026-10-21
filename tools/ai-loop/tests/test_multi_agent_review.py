"""Unit tests for the Multi-Agent Workflow Review mode (tools/ai-loop/multi_agent_review.py
+ the shared StructuredDrafter / GatedReviewer in shared/ai_loop.py), driven with a fake
proposer model and a scripted reviewer. No Ollama, no network, no Multi-Agent Server.

Run from the repository root:
    python -m pytest -q tools/ai-loop/tests
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "shared"))
sys.path.insert(0, str(HERE.parent))
import ai_loop  # noqa: E402
import multi_agent_review as mar  # noqa: E402
import review_common as common  # noqa: E402

_SPEC = importlib.util.spec_from_file_location("ai_loop_review", HERE.parent / "review.py")
review = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(review)

MODELS = {"planner": "qwen3:4b-instruct", "worker": "qwen3:4b-instruct", "reviewer": "qwen3:4b-instruct"}
EVIDENCE = {
    "mode": "vgarden-api",
    "passages": [
        {"chunk_id": "garden-1-summary", "title": "Backyard summary", "text": "Garden name: Backyard"},
        {"chunk_id": "garden-1-plantings", "title": "Backyard plantings", "text": "Tomato x3 - flowering"},
    ],
}


# --------------------------------------------------------------------------- #
# Builders: a history + audit + metrics export, event by event                #
# --------------------------------------------------------------------------- #


class Export:
    """Builds the three files the server exports, keeping history and audit in step."""

    def __init__(self):
        self.history: list[dict] = []
        self.audit: list[dict] = []
        self.sequence = 0
        self.runs: dict[str, str] = {}

    def event(self, workflow_id, status, details=None, *, run_id=None, models=None):
        self.sequence += 1
        details = details or {}
        if status == "planning":
            run_id = run_id or f"run-{self.sequence}"
            self.runs[workflow_id] = run_id
            details = {"run_id": run_id, "models": models or MODELS, "revision_feedback": "", **details}
        current = self.runs.get(workflow_id)
        self.history.append(
            {
                "sequence": self.sequence, "workflow_id": workflow_id, "status": status, "details": details,
                "created_at": f"2026-10-21T10:00:{self.sequence:02d}+00:00", "task": "Summarise the North bed.",
                "run_id": current, "models": (models or MODELS) if current else {},
            }
        )
        role = mar.STAGE_ROLE.get(status)
        self.audit.append(
            {
                "sequence": self.sequence, "workflow_id": workflow_id, "run_id": current,
                "created_at": self.history[-1]["created_at"], "event": status, "completed_role": role,
                "failed_role": None, "model": (models or MODELS).get(role) if role else None,
                "decision": details.get("human_review") or details.get("review"), "error": details.get("error"),
                "models": (models or MODELS) if status == "planning" else None,
            }
        )
        return self

    def full_run(self, workflow_id, *, recommendation="accept", issues=(), decision="accept", feedback="Checked.",
                 cited=("garden-1-plantings",), insufficient=False, evidence=EVIDENCE, steps=3):
        self.event(workflow_id, "planning")
        self.event(workflow_id, "working", {"plan": {"steps": ["step"] * steps}})
        self.event(
            workflow_id, "reviewing",
            {"result": {"answer": "Tomato x3 flowering.", "cited_chunk_ids": list(cited), "insufficient_context": insufficient},
             "evidence": evidence},
        )
        self.event(workflow_id, "awaiting_human_review", {"review": {"recommendation": recommendation, "issues": list(issues)}})
        if decision:
            status = {"accept": "accepted", "partially_accept": "partially_accepted", "reject": "rejected",
                      "request_changes": "changes_requested"}[decision]
            self.event(workflow_id, status, {"human_review": {"decision": decision, "feedback": feedback, "reviewer_id": "tester"}})
        return self

    def workflow(self, workflow_id, **kwargs):
        self.event(workflow_id, "received", {"source": "vgarden", "evidence": EVIDENCE})
        return self.full_run(workflow_id, **kwargs)

    def metrics(self):
        finals = {}
        for row in self.history:
            finals[row["workflow_id"]] = row["status"]
        states = {}
        for status in finals.values():
            states[status] = states.get(status, 0) + 1
        closed = sum(1 for s in finals.values() if s in mar.FINAL_STATES)
        return {
            "generated_at": "2026-10-21T10:30:00+00:00", "tracked_workflows": len(finals),
            "run_attempts": len(self.runs), "current_states": states,
            "handoff_success_rate": {"value": 1.0}, "workflow_completion_rate": {"numerator": closed, "denominator": len(finals), "value": 1.0},
            "human_approval_rate": {"value": 1.0}, "human_requested_revision_runs": 0, "rework_ratio": {"value": 0.0},
            "reviewer_defect_yield": {"reviews": len(self.runs), "reviews_with_issues": 0},
            "stage_execution_times": {"planner": {"mean_seconds": 10.0}, "worker": {"mean_seconds": 8.0}, "reviewer": {"mean_seconds": 5.0}},
        }

    def evidence(self, *, metrics=True, audit=True):
        return {
            "history": list(self.history), "audit": list(self.audit) if audit else [],
            "metrics": self.metrics() if metrics else None,
            "source": {"kind": "files", "directory": "docs/evidence/test", "files": {"workflow_history.jsonl": "x"}, "skipped_lines": 0},
        }

    def write(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True)
        (directory / mar.HISTORY_FILE).write_text("".join(json.dumps(r) + "\n" for r in self.history), encoding="utf-8")
        (directory / mar.AUDIT_FILE).write_text("".join(json.dumps(r) + "\n" for r in self.audit), encoding="utf-8")
        (directory / mar.METRICS_FILE).write_text(json.dumps(self.metrics()), encoding="utf-8")
        return directory


def clean_export() -> Export:
    export = Export().workflow("wf-a", recommendation="revise", issues=["unsupported claim"], decision="accept",
                               feedback="Checked against the garden records")
    export.event("wf-b", "received", {"source": "vgarden", "evidence": EVIDENCE})
    export.full_run("wf-b", recommendation="revise", issues=["x"], decision="request_changes", feedback="Also count the tomatoes.")
    export.full_run("wf-b", recommendation="accept", decision="accept", feedback="")
    return export


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
        return {"verdict": "revise", "issues": ["evidence not in grounding"], "guidance": "name the workflow id"}


def pass_draft(**overrides) -> dict:
    draft = {
        "decision": "pass",
        "workflows_reviewed": 2,
        "findings": [],
        "recommendations": ["Keep requiring a reason when the Reviewer says revise."],
        "summary": "Two workflows and three runs reviewed from files; every run reached a human decision.",
    }
    draft.update(overrides)
    return draft


def finding(**overrides) -> dict:
    base = {"severity": "low", "check": "coordination", "workflow_id": "wf-a", "evidence": "run 1: models recorded", "recommendation": "keep"}
    base.update(overrides)
    return base


def drafter_with(model) -> mar.MultiAgentDrafter:
    return mar.MultiAgentDrafter(call_model=model)


def run_loop(evidence, model, reviewer, tmp_path, **kwargs):
    return mar.review(evidence, drafter_with(model), reviewer, str(tmp_path), **kwargs)


# --------------------------------------------------------------------------- #
# Loading                                                                     #
# --------------------------------------------------------------------------- #


def test_loads_the_three_export_files_from_a_folder(tmp_path):
    directory = clean_export().write(tmp_path / "export")
    (directory / mar.HISTORY_FILE).open("a", encoding="utf-8").write("not json\n")

    evidence = mar.load_evidence_dir(directory)

    assert len(evidence["history"]) == 17 and len(evidence["audit"]) == 17
    assert evidence["metrics"]["tracked_workflows"] == 2
    assert evidence["source"]["kind"] == "files" and evidence["source"]["skipped_lines"] == 1
    assert set(evidence["source"]["files"]) == {mar.HISTORY_FILE, mar.AUDIT_FILE, mar.METRICS_FILE}


def test_a_missing_history_file_is_a_clear_error(tmp_path):
    with pytest.raises(SystemExit, match="workflow_history.jsonl"):
        mar.load_evidence_dir(tmp_path)


def test_loads_the_live_server_export_through_its_audit_routes():
    export = clean_export()
    urls = []

    def fetch(url):
        urls.append(url)
        if url.endswith(mar.HISTORY_FILE):
            return "".join(json.dumps(r) + "\n" for r in export.history).encode()
        if url.endswith(mar.AUDIT_FILE):
            return "".join(json.dumps(r) + "\n" for r in export.audit).encode()
        if url.endswith("/workflow/metrics"):
            return json.dumps(export.metrics()).encode()
        return json.dumps({"workflow_id": "wf-b", "status": "accepted", "source": "vgarden", "task": "t"}).encode()

    evidence = mar.load_evidence_server("http://127.0.0.1:8003/", workflow_id="wf-b", fetch=fetch)

    assert urls == [
        "http://127.0.0.1:8003/workflow/audit/workflow_history.jsonl",
        "http://127.0.0.1:8003/workflow/audit/coordination_audit.jsonl",
        "http://127.0.0.1:8003/workflow/metrics",
        "http://127.0.0.1:8003/workflow/status?id=wf-b",
    ]
    assert evidence["source"]["kind"] == "server" and evidence["source"]["live_status"]["status"] == "accepted"
    grounding, plan = mar.build_grounding(evidence, "wf-b")
    assert [wf["workflow_id"] for wf in grounding["workflows"]] == ["wf-b"]
    assert plan["workflows"] == 1 and plan["runs"] == 2
    # the metrics cover every workflow, so they are not cross-checked against one
    assert not [c for c in grounding["code_checks"] if c["check"] == "metrics_consistency"]


def test_http_get_refuses_non_http_urls():
    with pytest.raises(ValueError):
        common.http_get("file:///etc/passwd")


# --------------------------------------------------------------------------- #
# PLAN: the per-workflow records and code checks                              #
# --------------------------------------------------------------------------- #


def test_grounding_folds_the_history_into_runs_and_passes_a_clean_export():
    grounding, plan = mar.build_grounding(clean_export().evidence())

    assert plan == {
        "source": "files", "workflows": 2, "runs": 3, "human_decisions": 3, "reviewer_revise": 2,
        "code_findings": "high=0 medium=0 low=0", "evidence_gaps": 0,
    }
    assert grounding["code_checks"] == [] and grounding["evidence_gaps"] == []
    wf_b = grounding["workflows"][1]
    assert wf_b["final_status"] == "accepted" and len(wf_b["runs"]) == 2
    first, second = wf_b["runs"]
    assert first["stages"] == ["planning", "working", "reviewing", "awaiting_human_review", "changes_requested"]
    assert first["reviewer_recommendation"] == "revise" and first["human_decision"] == "request_changes"
    assert first["human_feedback"] == "Also count the tomatoes."
    assert second["cited_chunk_ids"] == ["garden-1-plantings"]
    assert second["evidence_chunk_ids"] == ["garden-1-summary", "garden-1-plantings"]
    assert second["models"] == MODELS
    assert grounding["totals"]["human_decisions"] == {"accept": 2, "request_changes": 1}
    assert grounding["metrics"]["tracked_workflows"] == 2
    # bulky passages stay out of the model's context
    assert "passages" not in json.dumps(grounding)


def test_a_revise_closed_without_a_reason_is_a_high_finding():
    export = Export().workflow("wf-a", recommendation="revise", issues=["x"], decision="accept", feedback="")

    checks = mar.build_grounding(export.evidence())[0]["code_checks"]

    assert [(c["severity"], c["check"]) for c in checks] == [("high", "revise_followed_by_reason")]
    assert "human_feedback = ''" in checks[0]["evidence"]


def test_a_pending_human_decision_is_medium_but_an_abandoned_one_is_high():
    pending = Export().workflow("wf-a", decision=None)
    checks = mar.build_grounding(pending.evidence())[0]["code_checks"]
    assert [(c["severity"], c["check"]) for c in checks if c["workflow_id"] == "wf-a"] == [("medium", "human_decision")]
    assert "(pending)" in checks[0]["evidence"]

    abandoned = Export().workflow("wf-a", decision=None)
    abandoned.full_run("wf-a")  # a second run started without closing the first
    checks = mar.build_grounding(abandoned.evidence())[0]["code_checks"]
    assert [(c["severity"], c["check"]) for c in checks if c["check"] == "human_decision"] == [("high", "human_decision")]


def test_worker_citations_must_point_at_the_evidence():
    outside = Export().workflow("wf-a", cited=("garden-9-plantings",))
    checks = mar.build_grounding(outside.evidence())[0]["code_checks"]
    assert [(c["severity"], c["check"]) for c in checks] == [("high", "worker_citations")]
    assert "garden-9-plantings" in checks[0]["evidence"]

    uncited = Export().workflow("wf-a", cited=(), insufficient=False)
    checks = mar.build_grounding(uncited.evidence())[0]["code_checks"]
    assert [(c["severity"], c["check"]) for c in checks] == [("medium", "worker_citations")]

    unverifiable = Export()
    unverifiable.event("wf-a", "received", {"source": "almanac"})
    unverifiable.full_run("wf-a", cited=("almanac-tomato",), evidence=None)
    checks = mar.build_grounding(unverifiable.evidence())[0]["code_checks"]
    assert [(c["severity"], c["check"]) for c in checks] == [("low", "worker_citations")]


def test_interrupted_and_failed_runs_are_stage_sequence_findings():
    interrupted = Export()
    interrupted.event("wf-a", "received", {"source": "vgarden", "evidence": EVIDENCE})
    interrupted.event("wf-a", "planning")
    interrupted.event("wf-a", "working", {"plan": {"steps": ["s"]}})
    checks = mar.build_grounding(interrupted.evidence())[0]["code_checks"]
    assert [(c["severity"], c["check"]) for c in checks if c["workflow_id"] == "wf-a"] == [("medium", "stage_sequence")]
    assert "reviewing, awaiting_human_review never recorded" in checks[0]["evidence"]

    failed_then_recovered = Export()
    failed_then_recovered.event("wf-a", "received", {"source": "vgarden", "evidence": EVIDENCE})
    failed_then_recovered.event("wf-a", "planning")
    failed_then_recovered.event("wf-a", "working", {"plan": {"steps": ["s"]}})
    failed_then_recovered.event("wf-a", "failed", {"error": "worker failed"})
    failed_then_recovered.full_run("wf-a")
    grounding = mar.build_grounding(failed_then_recovered.evidence())[0]
    assert grounding["workflows"][0]["runs"][0]["failed_at"] == "worker"
    assert [(c["severity"], c["check"]) for c in grounding["code_checks"] if c["workflow_id"] == "wf-a"] == [("low", "stage_sequence")]


def test_missing_models_and_empty_plans_are_coordination_findings():
    export = Export()
    export.event("wf-a", "received", {"source": "vgarden", "evidence": EVIDENCE})
    export.full_run("wf-a", steps=0)
    export.history[1]["details"]["models"] = {"planner": "qwen3:4b-instruct"}

    checks = [c for c in mar.build_grounding(export.evidence(audit=False))[0]["code_checks"] if c["check"] == "coordination"]

    assert [c["severity"] for c in checks] == ["medium", "medium"]
    assert "no steps" in checks[0]["evidence"] and "worker, reviewer" in checks[1]["evidence"]


def test_audit_and_metrics_are_cross_checked_against_the_history():
    export = clean_export()
    evidence = export.evidence()
    evidence["audit"] = evidence["audit"][:-1]  # one hand-off missing from the audit
    evidence["metrics"]["tracked_workflows"] = 5
    evidence["metrics"]["current_states"] = {"accepted": 5}

    checks = mar.build_grounding(evidence)[0]["code_checks"]

    assert [(c["severity"], c["check"]) for c in checks] == [
        ("medium", "audit_consistency"), ("medium", "metrics_consistency"), ("medium", "metrics_consistency"),
    ]
    assert checks[0]["workflow_id"] == "wf-b" and "history has 11 events, audit has 10" in checks[0]["evidence"]
    assert "tracked_workflows = 5" in checks[1]["evidence"]

    no_audit = mar.build_grounding(export.evidence(audit=False, metrics=False))[0]["code_checks"]
    assert [(c["severity"], c["check"]) for c in no_audit] == [("medium", "audit_consistency"), ("low", "metrics_consistency")]


# --------------------------------------------------------------------------- #
# Refusal in code, without a model call                                       #
# --------------------------------------------------------------------------- #


def test_refuses_when_the_history_has_no_workflows(tmp_path):
    evidence = {"history": [], "audit": [], "metrics": None, "source": {"kind": "files"}}
    model = FakeModel(pass_draft())
    reviewer = FakeReviewer("approved")

    decision, result = run_loop(evidence, model, reviewer, tmp_path)

    assert model.calls == [] and reviewer.drafts == []
    assert decision["decision"] == "insufficient_evidence" and decision["workflows_reviewed"] == 0
    assert decision["findings"][0]["severity"] == "high" and "no workflows" in decision["findings"][0]["evidence"]
    assert result.verdict == "approved" and result.iterations == 1
    observe = next(e for e in result.trace if e["phase"] == "observe")
    assert "reviewer model not consulted" in observe["issues"]
    assert mar.validate(decision) == []


def test_refuses_when_the_selected_workflow_is_absent(tmp_path):
    decision, _ = run_loop(clean_export().evidence(), FakeModel(pass_draft()), None, tmp_path, workflow_id="wf-zzz")

    assert decision["decision"] == "insufficient_evidence"
    assert "wf-zzz is not in the history" in decision["findings"][0]["evidence"]


def test_a_draft_that_is_not_the_refusal_is_sent_back_when_evidence_is_missing():
    grounding, _ = mar.build_grounding({"history": [], "audit": [], "metrics": None, "source": {}})
    gate = ai_loop.GatedReviewer(None, mar.refusal)

    verdict = gate.review("q", grounding, json.dumps(pass_draft()))

    assert verdict["verdict"] == "revise" and "fixed refusal" in verdict["issues"][0]
    with pytest.raises(ai_loop.LoopError):
        ai_loop.GatedReviewer(None, mar.refusal).review("q", mar.build_grounding(clean_export().evidence())[0], "{}")


# --------------------------------------------------------------------------- #
# Schema validation and normalisation of the model's output                  #
# --------------------------------------------------------------------------- #


def test_schema_pins_the_enums():
    schema = mar.SCHEMA
    assert schema["required"] == ["decision", "workflows_reviewed", "findings", "recommendations", "summary"]
    assert schema["properties"]["decision"]["enum"] == list(common.DECISIONS)
    item = schema["properties"]["findings"]["items"]
    assert item["properties"]["check"]["enum"] == list(mar.CHECKS)
    assert item["properties"]["severity"]["enum"] == ["high", "medium", "low"]


@pytest.mark.parametrize(
    "bad, message",
    [
        ("nope", "must be a JSON object"),
        (pass_draft(decision="maybe"), "decision must be one of"),
        (pass_draft(workflows_reviewed="2"), "workflows_reviewed must be a non-negative integer"),
        (pass_draft(summary=""), "summary must be a non-empty string"),
        (pass_draft(recommendations="do it"), "recommendations must be a list of strings"),
        (pass_draft(findings={}), "findings must be a list"),
        (pass_draft(findings=["x"]), "findings[0] must be an object"),
        (pass_draft(findings=[finding(severity="urgent")]), "severity must be high, medium or low"),
        (pass_draft(findings=[finding(check="vibes")]), "check must be one of"),
        (pass_draft(findings=[finding(workflow_id=7)]), "workflow_id must be a string"),
        (pass_draft(findings=[finding(evidence="")]), "evidence must be a non-empty string"),
    ],
)
def test_validate_rejects_shapes_outside_the_schema(bad, message):
    assert any(message in problem for problem in mar.validate(bad)), mar.validate(bad)


def test_invalid_model_output_is_a_loop_error_not_a_decision():
    grounding, _ = mar.build_grounding(clean_export().evidence())
    with pytest.raises(ai_loop.LoopError, match="invalid decision"):
        drafter_with(FakeModel({"decision": "pass"})).draft("q", grounding)


def test_code_findings_the_model_omitted_are_added_and_the_decision_corrected():
    export = Export().workflow("wf-a", recommendation="revise", issues=["x"], decision="accept", feedback="")
    grounding, _ = mar.build_grounding(export.evidence())
    corrections: list[str] = []

    decision = mar.normalise(pass_draft(workflows_reviewed=3), grounding, corrections)

    assert decision["decision"] == "fail" and decision["workflows_reviewed"] == 1
    assert [f["check"] for f in decision["findings"]] == ["revise_followed_by_reason"]
    assert "added the missing high finding revise_followed_by_reason for wf-a" in corrections
    assert "pass is inconsistent with the findings -> fail" in corrections
    assert "workflows_reviewed corrected to 1 from the grounding" in corrections
    assert decision["summary"].startswith("Corrected in code to fail: ")
    assert "The model's draft said:" in decision["summary"]


def test_findings_about_unknown_workflows_are_dropped_and_severities_follow_the_code():
    export = Export().workflow("wf-a", cited=("garden-9-plantings",))
    grounding, _ = mar.build_grounding(export.evidence())
    corrections: list[str] = []
    raw = pass_draft(
        decision="pass_with_findings",
        workflows_reviewed=1,
        findings=[
            finding(check="worker_citations", severity="low", evidence="wf-a cited garden-9-plantings"),
            finding(workflow_id="wf-ghost", evidence="made up"),
            finding(workflow_id="", check="metrics_consistency", evidence="metrics generated after the export"),
        ],
    )

    decision = mar.normalise(raw, grounding, corrections)

    assert [f["workflow_id"] for f in decision["findings"]] == ["wf-a"]
    assert decision["findings"][0]["severity"] == "high"  # the code's severity, the model's wording
    assert decision["findings"][0]["evidence"] == "wf-a cited garden-9-plantings"
    assert decision["decision"] == "fail"
    assert any("dropped finding 'made up'" in note for note in corrections)
    assert any("metrics_consistency check holds for *" in note for note in corrections)
    assert "severity of worker_citations for wf-a set to high (code check), the draft said low" in corrections
    assert decision["summary"].startswith("2 finding(s) in the model's draft were not confirmed")


def test_model_findings_the_code_did_not_confirm_are_dropped():
    grounding, _ = mar.build_grounding(clean_export().evidence())
    corrections: list[str] = []
    raw = pass_draft(
        decision="fail",
        findings=[finding(check="revise_followed_by_reason", severity="high", workflow_id="wf-a", evidence="no reason given")],
    )

    decision = mar.normalise(raw, grounding, corrections)

    assert decision["findings"] == [] and decision["decision"] == "pass"
    assert corrections[0].startswith("dropped finding 'no reason given': the revise_followed_by_reason check holds for wf-a")
    assert "fail is inconsistent with the findings -> pass" in corrections
    assert "1 finding(s) in the model's draft were not confirmed" in decision["summary"]


def test_a_run_id_used_as_the_workflow_id_is_mapped_to_its_workflow():
    export = Export().workflow("wf-a", recommendation="revise", issues=["x"], decision="accept", feedback="")
    grounding, _ = mar.build_grounding(export.evidence())
    run_id = grounding["workflows"][0]["runs"][0]["run_id"]
    corrections: list[str] = []
    raw = pass_draft(decision="fail", workflows_reviewed=1, findings=[
        finding(check="revise_followed_by_reason", severity="high", workflow_id=run_id, evidence="revise closed without a reason"),
    ])

    decision = mar.normalise(raw, grounding, corrections)

    assert [(f["workflow_id"], f["evidence"]) for f in decision["findings"]] == [("wf-a", "revise closed without a reason")]
    assert any(note.startswith("mapped workflow_id") for note in corrections)
    assert not any("added the missing" in note for note in corrections)


def test_low_code_findings_are_informational():
    grounding, _ = mar.build_grounding(clean_export().evidence(metrics=False))
    assert [c["severity"] for c in grounding["code_checks"]] == ["low"]
    decision = mar.normalise(pass_draft(findings=[]), grounding, [])
    assert decision["decision"] == "pass" and [f["check"] for f in decision["findings"]] == ["metrics_consistency"]


def test_a_draft_with_findings_but_no_recommendations_gets_the_fallback_one():
    export = Export().workflow("wf-a", decision=None)
    grounding, _ = mar.build_grounding(export.evidence())
    corrections: list[str] = []

    decision = mar.normalise(
        pass_draft(decision="pass_with_findings", workflows_reviewed=1, recommendations=[],
                   findings=[finding(check="human_decision", severity="medium", evidence="pending")]),
        grounding, corrections,
    )

    assert decision["recommendations"] == [mar.FALLBACK_RECOMMENDATION]
    assert decision["decision"] == "pass_with_findings"
    assert "fallback recommendation" in corrections[0]


def test_the_model_may_not_refuse_when_there_is_evidence():
    grounding, _ = mar.build_grounding(clean_export().evidence())
    decision = mar.normalise(pass_draft(decision="insufficient_evidence"), grounding, [])
    assert decision["decision"] == "pass"


# --------------------------------------------------------------------------- #
# The loop: Plan -> Act -> Observe -> Adapt with feedback threading           #
# --------------------------------------------------------------------------- #


def test_a_clean_export_passes_in_one_iteration(tmp_path):
    model = FakeModel(pass_draft())
    reviewer = FakeReviewer("approved")

    decision, result = run_loop(clean_export().evidence(), model, reviewer, tmp_path)

    assert decision["decision"] == "pass" and decision["findings"] == []
    assert result.verdict == "approved" and result.iterations == 1
    assert [e["phase"] for e in result.trace] == ["plan", "act", "observe", "adapt"]
    system, context = model.calls[0]
    assert system == mar.PROMPT_ACT and "code_checks" in context["grounding"] and context["task"] == mar.QUESTION
    assert reviewer.drafts == [decision]


def test_reviewer_feedback_is_threaded_into_the_next_draft(tmp_path):
    model = FakeModel(pass_draft(summary="first"), pass_draft(summary="second"))

    decision, result = run_loop(clean_export().evidence(), model, FakeReviewer("revise", "approved"), tmp_path)

    assert result.iterations == 2 and result.verdict == "approved"
    assert decision["summary"] == "second"
    assert "reviewer_feedback" not in model.calls[0][1]
    assert "name the workflow id" in model.calls[1][1]["reviewer_feedback"]
    assert [e["phase"] for e in result.trace] == ["plan", "act", "observe", "adapt", "act", "observe", "adapt"]


def test_code_corrections_force_a_deterministic_revision_before_the_model_reviewer(tmp_path):
    invented = pass_draft(decision="fail", findings=[
        finding(check="human_decision", severity="high", workflow_id="wf-b", evidence="no decision recorded"),
    ])
    model = FakeModel(invented, pass_draft())
    reviewer = FakeReviewer("approved")

    decision, result = run_loop(clean_export().evidence(), model, reviewer, tmp_path)

    assert decision["decision"] == "pass" and result.iterations == 2 and result.verdict == "approved"
    observes = [e for e in result.trace if e["phase"] == "observe"]
    assert observes[0]["verdict"] == "revise" and "deterministic check: the code had to correct the draft" in observes[0]["issues"]
    assert observes[1]["verdict"] == "approved"
    assert reviewer.drafts == [pass_draft()]  # the model reviewer only saw the consistent draft
    assert "Corrections made: dropped finding 'no decision recorded'" in model.calls[1][1]["reviewer_feedback"]


def test_the_cap_returns_the_last_normalised_draft(tmp_path):
    decision, result = run_loop(clean_export().evidence(), FakeModel(pass_draft()), FakeReviewer("revise"), tmp_path, max_iterations=2)
    assert result.verdict == "revised_capped" and result.iterations == 2 and decision["decision"] == "pass"


def test_without_a_reviewer_a_real_review_is_the_single_shot_fallback(tmp_path):
    decision, result = run_loop(clean_export().evidence(), FakeModel(pass_draft()), None, tmp_path)
    assert result.verdict == "fallback" and decision["decision"] == "pass"


def test_every_phase_reaches_the_jsonl_and_the_transcript(tmp_path):
    _, result = run_loop(clean_export().evidence(), FakeModel(pass_draft()), FakeReviewer(), tmp_path)

    lines = (tmp_path / "multi-agent.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["phase"] for line in lines] == ["plan", "act", "observe", "adapt"]
    assert json.loads(lines[0])["workflows"] == 2
    transcript = Path(result.transcript_path).read_text(encoding="utf-8")
    assert transcript.startswith("# Agentic loop run `multi-agent-") and "## OBSERVE" in transcript


# --------------------------------------------------------------------------- #
# The runner: review.py --mode multi-agent, validation log and copies         #
# --------------------------------------------------------------------------- #


def test_run_writes_the_validation_log_and_the_summary(tmp_path):
    directory = clean_export().write(tmp_path / "export")
    args = review.build_parser().parse_args(
        ["--mode", "multi-agent", "--evidence-dir", str(directory), "--log-dir", str(tmp_path / "logs"),
         "--copy-dir", str(tmp_path / "copies"), "--model", "fake", "--review-model", "fake-reviewer"]
    )

    summary = mar.run(args, drafter=drafter_with(FakeModel(pass_draft())), reviewer=FakeReviewer())

    assert summary["mode"] == "multi-agent" and summary["decision"]["decision"] == "pass"
    assert summary["models"] == {"proposer": "fake", "reviewer": "fake-reviewer", "ollama_url": args.ollama_url}
    assert summary["loop"]["verdict"] == "approved" and summary["code_checks"] == []
    md_path = Path(summary["validation_log"]["markdown"])
    assert md_path.parent == tmp_path / "copies" and md_path.name.startswith("multi-agent-") and md_path.name.endswith("-review.md")
    log = md_path.read_text(encoding="utf-8")
    for heading in ("# Multi-Agent Workflow Review — validation log", "## Decision", "## Findings",
                    "## Implementation and review recommendations", "## Workflows reviewed", "## Checks computed in code",
                    "## Code corrections applied to the final draft", "## Loop trace", "## Human confirmation"):
        assert heading in log
    assert "| **pass** | 2 |" in log and "`wf-b`" in log and "request_changes (reason), accept" in log
    saved = json.loads(Path(summary["validation_log"]["json"]).read_text(encoding="utf-8"))
    assert saved["decision"] == summary["decision"] and saved["validation_log"] == summary["validation_log"]
    assert (tmp_path / "copies" / "multi-agent-latest-review.md").read_text(encoding="utf-8") == log
    assert review.EXIT_CODES[summary["decision"]["decision"]] == 0


def test_run_reports_failures_with_exit_code_one(tmp_path):
    export = Export().workflow("wf-a", recommendation="revise", issues=["x"], decision="accept", feedback="")
    directory = export.write(tmp_path / "export")
    args = review.build_parser().parse_args(
        ["--mode", "multi-agent", "--evidence-dir", str(directory), "--log-dir", str(tmp_path / "logs"), "--no-copy"]
    )

    summary = mar.run(args, drafter=drafter_with(FakeModel(pass_draft(workflows_reviewed=1))), reviewer=FakeReviewer())

    assert summary["decision"]["decision"] == "fail" and summary["validation_log"] is None
    assert summary["code_checks"][0]["check"] == "revise_followed_by_reason"
    assert any("added the missing high finding" in note for note in summary["code_corrections"])
    # the model never included the code finding, so the deterministic OBSERVE kept asking until the cap
    assert summary["loop"]["verdict"] == "revised_capped" and summary["loop"]["iterations"] == 2
    assert review.EXIT_CODES["fail"] == 1 and review.EXIT_CODES["insufficient_evidence"] == 2


def test_main_registers_the_mode_and_maps_the_decision_to_the_exit_code(tmp_path, monkeypatch, capsys):
    monkeypatch.setitem(review.MODES, "multi-agent", lambda args: {"mode": "multi-agent", "decision": {"decision": "pass_with_findings"}})
    assert review.main(["--mode", "multi-agent", "--output", str(tmp_path / "out.json")]) == 0
    assert json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))["decision"]["decision"] == "pass_with_findings"

    monkeypatch.setitem(review.MODES, "multi-agent", lambda args: {"mode": "multi-agent", "decision": {"decision": "fail"}})
    assert review.main(["--mode", "multi-agent"]) == 1
    assert "fail" in capsys.readouterr().out

    with pytest.raises(SystemExit):
        review.main(["--mode", "multi-agent", "--server", "ftp://nope"])

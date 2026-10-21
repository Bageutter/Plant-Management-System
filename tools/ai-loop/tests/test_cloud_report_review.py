"""Unit tests for the Cloud Deployment Report Review mode (shared/ai_loop.py +
tools/ai-loop/cloud_report_review.py), driven with a fake proposer model and a
scripted reviewer. No Ollama, no network.

    python -m unittest discover -s tools/ai-loop/tests      # what vgarden.yml runs
    python -m pytest -q tools/ai-loop/tests                 # also fine
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "shared"))
sys.path.insert(0, str(HERE.parent))
import ai_loop  # noqa: E402
import cloud_report_review as review  # noqa: E402

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


def finding(severity="low", area="container_apps", evidence="container_apps[1].minReplicas = 0", recommendation="y"):
    return {"severity": severity, "area": area, "evidence": evidence, "recommendation": recommendation}


def drafter_with(model: FakeModel) -> ai_loop.CloudDeploymentDrafter:
    return ai_loop.CloudDeploymentDrafter(call_model=model)


def grounding_for(report: dict) -> dict:
    return ai_loop.build_cloud_deployment_grounding(report)[0]


class TempDirCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def run_loop(self, report, model, reviewer, max_iterations=2):
        drafter = drafter_with(model)
        decision, result = ai_loop.review_cloud_deployment(
            report, drafter, reviewer, str(self.tmp), max_iterations=max_iterations
        )
        return decision, result, drafter


# --------------------------------------------------------------------------- #
# Grounding (PLAN)                                                            #
# --------------------------------------------------------------------------- #


class Grounding(unittest.TestCase):
    def test_selects_the_reviewable_facts_only(self):
        grounding, plan = ai_loop.build_cloud_deployment_grounding(sample_report())

        self.assertTrue(grounding["deployment"]["commit"].startswith("0a31150"))
        self.assertTrue(grounding["deployment"]["workflow_run_url"].startswith("https://"))
        self.assertEqual(set(grounding["endpoints"]["public_urls"]), {"auth", "vgarden", "almanac", "health"})
        self.assertEqual(grounding["cloud_baseline"], {flag: False for flag in ai_loop.CLOUD_BASELINE_FLAGS})
        self.assertEqual(grounding["smoke_test"], {"result": "pass"})
        self.assertEqual(grounding["container_apps"][0]["name"], "pms-proxy")
        self.assertEqual(
            set(grounding["container_apps"][0]),
            {"name", "external", "allowInsecure", "image", "revision", "status", "minReplicas", "maxReplicas"},
        )
        self.assertEqual(grounding["postgres"][0]["publicNetworkAccess"], "Disabled")
        self.assertEqual(grounding["key_vaults"][0], {"name": "pms-kv-release2", "rbac": True, "softDelete": True})
        self.assertIs(grounding["storage_accounts"][0]["blobPublicAccess"], False)
        self.assertEqual(len(grounding["security_controls"]), 8)
        self.assertEqual(grounding["evidence_gaps"], [])
        # bulky, non-reviewable sections stay out of the model's context
        self.assertNotIn("resources", grounding)
        self.assertNotIn("platform_outputs", grounding)
        self.assertNotIn("internal_fqdns", grounding["endpoints"])
        self.assertEqual((plan["smoke_result"], plan["evidence_gaps"], plan["container_apps"]), ("pass", 0, 5))

    def test_rejects_a_non_object_report(self):
        with self.assertRaises(ValueError):
            ai_loop.build_cloud_deployment_grounding(["not", "a", "report"])

    def test_a_partial_flag_set_names_only_the_missing_flags(self):
        report = sample_report()
        report["cloud_baseline"] = {"ai_mode_enabled": False, "mcp_enabled": "false"}  # a string is not a flag

        grounding = grounding_for(report)

        self.assertIs(grounding["cloud_baseline"]["ai_mode_enabled"], False)
        self.assertIsNone(grounding["cloud_baseline"]["mcp_enabled"])
        self.assertEqual(len(grounding["evidence_gaps"]), 1)
        self.assertIn("mcp_enabled, rag_enabled, multi_agent_enabled", grounding["evidence_gaps"][0])

    def test_both_gaps_produce_two_refusal_findings(self):
        report = sample_report()
        report["smoke_test"] = {}
        report["cloud_baseline"] = {}

        refusal = ai_loop.cloud_deployment_refusal(grounding_for(report))

        self.assertEqual(refusal["decision"], "insufficient_evidence")
        self.assertEqual([f["area"] for f in refusal["findings"]], ["smoke_test", "cloud_baseline"])
        self.assertEqual(ai_loop.validate_cloud_decision(refusal), [])


# --------------------------------------------------------------------------- #
# Refusals: insufficient evidence, decided in code without a model call       #
# --------------------------------------------------------------------------- #


class Refusals(TempDirCase):
    def test_refuses_when_the_smoke_result_is_missing(self):
        report = sample_report()
        report["smoke_test"] = {"result": "unknown"}
        model = FakeModel(approve_draft())
        reviewer = FakeReviewer("approved")

        decision, result, _ = self.run_loop(report, model, reviewer)

        self.assertEqual(model.calls, [])  # nothing to guess from -> the proposer is never asked
        self.assertEqual(decision["decision"], "insufficient_evidence")
        self.assertIs(decision["baseline_compliant"], False)
        self.assertEqual([f["area"] for f in decision["findings"]], ["smoke_test"])
        self.assertEqual(decision["findings"][0]["severity"], "high")
        self.assertIn("smoke_test.result", decision["findings"][0]["evidence"])
        self.assertTrue(decision["release_recommendation"].startswith("Insufficient evidence"))
        # OBSERVE is deterministic for a refusal: approved on the first pass, model reviewer unused
        self.assertEqual((result.verdict, result.iterations), ("approved", 1))
        self.assertEqual(reviewer.drafts, [])
        observe = next(e for e in result.trace if e["phase"] == "observe")
        self.assertEqual(observe["verdict"], "approved")
        self.assertIn("reviewer model not consulted", observe["issues"])

    def test_refuses_when_the_baseline_flags_are_missing(self):
        report = sample_report()
        del report["cloud_baseline"]
        model = FakeModel(approve_draft())

        decision, _, _ = self.run_loop(report, model, FakeReviewer())

        self.assertEqual(model.calls, [])
        self.assertEqual(decision["decision"], "insufficient_evidence")
        self.assertEqual([f["area"] for f in decision["findings"]], ["cloud_baseline"])
        self.assertIn("cloud_baseline flags missing", decision["findings"][0]["evidence"])
        for flag in ai_loop.CLOUD_BASELINE_FLAGS:
            self.assertIn(flag, decision["findings"][0]["evidence"])

    def test_refusal_is_checked_deterministically_even_without_a_review_model(self):
        report = sample_report()
        report["smoke_test"] = {"result": None}

        decision, result, _ = self.run_loop(report, FakeModel(approve_draft()), None)

        self.assertEqual(decision["decision"], "insufficient_evidence")
        self.assertEqual(result.verdict, "approved")  # not the single-shot fallback
        self.assertEqual([e["phase"] for e in result.trace], ["plan", "act", "observe", "adapt"])

    def test_a_draft_that_is_not_the_refusal_is_sent_back_when_evidence_is_missing(self):
        report = sample_report()
        report["smoke_test"] = {}
        reviewer = ai_loop.CloudDeploymentReviewer(None)

        verdict = reviewer.review("q", grounding_for(report), json.dumps(approve_draft()))

        self.assertEqual(verdict["verdict"], "revise")
        self.assertIn("fixed refusal", verdict["issues"][0])

    def test_reviewer_wrapper_delegates_real_reviews_to_the_model_reviewer(self):
        grounding = grounding_for(sample_report())
        inner = FakeReviewer("revise")

        verdict = ai_loop.CloudDeploymentReviewer(inner).review("q", grounding, json.dumps(approve_draft()))

        self.assertEqual(verdict["verdict"], "revise")
        self.assertEqual(inner.drafts, [approve_draft()])
        with self.assertRaises(ai_loop.LoopError):
            ai_loop.CloudDeploymentReviewer(None).review("q", grounding, json.dumps(approve_draft()))


# --------------------------------------------------------------------------- #
# Schema validation and normalisation of the model's output                  #
# --------------------------------------------------------------------------- #


class SchemaValidation(unittest.TestCase):
    def test_schema_constant_pins_the_enums(self):
        schema = ai_loop.CLOUD_DECISION_SCHEMA
        self.assertEqual(schema["required"], ["decision", "baseline_compliant", "findings", "release_recommendation"])
        self.assertEqual(schema["properties"]["decision"]["enum"], list(ai_loop.CLOUD_DECISIONS))
        item = schema["properties"]["findings"]["items"]
        self.assertEqual(item["properties"]["severity"]["enum"], ["high", "medium", "low"])
        self.assertEqual(item["properties"]["area"]["enum"], list(ai_loop.CLOUD_AREAS))
        self.assertEqual(item["required"], ["severity", "area", "evidence", "recommendation"])

    def test_rejects_shapes_outside_the_schema(self):
        cases = [
            ("not json object", "must be a JSON object"),
            (approve_draft(decision="maybe"), "decision must be one of"),
            (approve_draft(baseline_compliant="yes"), "baseline_compliant must be a boolean"),
            (approve_draft(release_recommendation=""), "release_recommendation must be a non-empty string"),
            (approve_draft(findings={"severity": "high"}), "findings must be a list"),
            (approve_draft(findings=["high"]), "findings[0] must be an object"),
            (approve_draft(findings=[finding(severity="urgent")]), "severity must be high, medium or low"),
            (approve_draft(findings=[finding(area="network")]), "area must be one of"),
            (approve_draft(findings=[finding(evidence="")]), "evidence must be a non-empty string"),
        ]
        for bad, message in cases:
            with self.subTest(message=message):
                problems = ai_loop.validate_cloud_decision(bad)
                self.assertTrue(any(message in problem for problem in problems), problems)

    def test_invalid_model_output_is_a_loop_error_not_a_decision(self):
        model = FakeModel({"decision": "approve"})  # missing the other required keys

        with self.assertRaisesRegex(ai_loop.LoopError, "invalid decision"):
            drafter_with(model).draft("q", grounding_for(sample_report()))

    def test_valid_output_is_normalised_and_clipped(self):
        raw = approve_draft(
            decision="approve_with_corrections",
            findings=[finding(evidence="  container_apps[1].minReplicas = 0 \n (scale to zero)  ", recommendation="x" * 500)],
        )

        decision = ai_loop.normalise_cloud_decision(raw, grounding_for(sample_report()))

        self.assertEqual(decision["decision"], "approve_with_corrections")
        self.assertIs(decision["baseline_compliant"], True)
        self.assertEqual(decision["findings"][0]["evidence"], "container_apps[1].minReplicas = 0 (scale to zero)")
        self.assertEqual(len(decision["findings"][0]["recommendation"]), ai_loop.CLOUD_MAX_FIELD_CHARS)
        self.assertEqual(ai_loop.validate_cloud_decision(decision), [])

    def test_model_may_not_refuse_when_the_evidence_is_complete(self):
        decision = ai_loop.normalise_cloud_decision(
            approve_draft(decision="insufficient_evidence"), grounding_for(sample_report())
        )
        self.assertEqual(decision["decision"], "reject")


# --------------------------------------------------------------------------- #
# Release rules enforced whatever the model said                              #
# --------------------------------------------------------------------------- #


class ReleaseRules(TempDirCase):
    def test_an_enabled_ai_service_is_a_baseline_breach(self):
        report = sample_report()
        report["cloud_baseline"]["mcp_enabled"] = True
        report["cloud_baseline"]["rag_enabled"] = True
        model = FakeModel(approve_draft())  # the model wrongly approves with no findings

        decision, _, drafter = self.run_loop(report, model, FakeReviewer())

        self.assertEqual(len(model.calls), 1)
        self.assertIs(decision["baseline_compliant"], False)
        self.assertEqual(decision["decision"], "approve_with_corrections")  # never "approve" with a breach
        self.assertIn("approve with an enabled baseline switch -> approve_with_corrections", drafter.last_corrections)
        self.assertIn("baseline_compliant corrected to False from the grounding flags", drafter.last_corrections)
        # the model's "no further action" prose may not stand under a corrected decision
        self.assertTrue(decision["release_recommendation"].startswith("Corrected in code to approve_with_corrections: "))
        self.assertIn("mcp_enabled", decision["release_recommendation"])
        self.assertIn("The model's draft said: Approve:", decision["release_recommendation"])
        breaches = [f for f in decision["findings"] if f["area"] == "cloud_baseline"]
        self.assertEqual({f["severity"] for f in breaches}, {"high"})
        self.assertTrue(any("mcp_enabled" in f["evidence"] for f in breaches))
        self.assertTrue(any("rag_enabled" in f["evidence"] for f in breaches))
        # the system prompt itself states the rule the code enforces
        self.assertIn("baseline breach", model.calls[0][0])

    def test_a_model_reported_breach_is_kept_not_duplicated(self):
        report = sample_report()
        report["cloud_baseline"]["ai_mode_enabled"] = True
        raw = approve_draft(
            decision="reject",
            baseline_compliant=False,
            findings=[finding("high", "cloud_baseline", "cloud_baseline.ai_mode_enabled = true", "Redeploy with AI-Mode off.")],
        )

        decision = ai_loop.normalise_cloud_decision(raw, grounding_for(report))

        self.assertEqual(decision["decision"], "reject")
        self.assertEqual(len(decision["findings"]), 1)
        self.assertEqual(decision["release_recommendation"], raw["release_recommendation"])

    def test_a_finding_that_contradicts_a_disabled_flag_is_dropped_and_recorded(self):
        """A live run claimed every switch was 'Enabled' while the grounding had all
        four false, and still said approve; the code must not pass that on."""
        model = FakeModel(
            approve_draft(
                findings=[
                    finding("high", "cloud_baseline", "ai_mode_enabled = Enabled", "Disable it."),
                    finding("low", "container_apps", "container_apps[1].minReplicas = 0", "Consider a warm replica."),
                ]
            )
        )

        decision, _, drafter = self.run_loop(sample_report(), model, FakeReviewer())

        self.assertEqual(decision["decision"], "approve")
        self.assertEqual([f["area"] for f in decision["findings"]], ["container_apps"])
        self.assertTrue(
            any(n.startswith("dropped finding") and "ai_mode_enabled=false" in n for n in drafter.last_corrections)
        )

    def test_approve_with_a_high_finding_becomes_approve_with_corrections(self):
        notes: list[str] = []
        raw = approve_draft(findings=[finding("high", "postgres", "postgres[0].backupRetentionDays = 7", "Raise to 14.")])

        decision = ai_loop.normalise_cloud_decision(raw, grounding_for(sample_report()), notes)

        self.assertEqual(decision["decision"], "approve_with_corrections")
        self.assertEqual(notes, ["approve with a high finding is inconsistent -> approve_with_corrections"])

    def test_corrections_are_recorded_for_the_refusal_and_for_a_clean_draft(self):
        gap_report = sample_report()
        gap_report["smoke_test"] = {}
        drafter = drafter_with(FakeModel(approve_draft()))

        drafter.draft("q", grounding_for(gap_report))
        self.assertEqual(drafter.last_corrections, ["evidence gaps -> fixed insufficient_evidence decision, no model call"])

        drafter.draft("q", grounding_for(sample_report()))
        self.assertEqual(drafter.last_corrections, [])

    def test_a_failed_smoke_test_rejects(self):
        report = sample_report()
        report["smoke_test"]["result"] = "FAIL"

        decision, _, _ = self.run_loop(report, FakeModel(approve_draft()), FakeReviewer())

        self.assertEqual(decision["decision"], "reject")
        self.assertEqual(
            decision["findings"][0],
            {
                "severity": "high",
                "area": "smoke_test",
                "evidence": "smoke_test.result = fail",
                "recommendation": "Fix the failing endpoint, redeploy and re-run scripts/deploy/azure-smoke.sh.",
            },
        )
        self.assertTrue(decision["release_recommendation"].startswith("Corrected in code to reject: smoke_test.result = fail"))


# --------------------------------------------------------------------------- #
# The loop: feedback threading and the three evidence sinks                   #
# --------------------------------------------------------------------------- #


class Loop(TempDirCase):
    def test_reviewer_guidance_is_carried_into_the_next_draft(self):
        model = FakeModel(approve_draft(), approve_draft(release_recommendation="Approve (revised)."))

        decision, result, _ = self.run_loop(sample_report(), model, FakeReviewer("revise", "approved"))

        self.assertEqual((result.iterations, result.verdict), (2, "approved"))
        self.assertNotIn("reviewer_feedback", model.calls[0][1])
        self.assertIn("cite a grounding value", model.calls[1][1]["reviewer_feedback"])
        self.assertEqual(model.calls[1][1]["grounding"]["smoke_test"], {"result": "pass"})
        self.assertEqual(decision["release_recommendation"], "Approve (revised).")

    def test_no_reviewer_is_a_logged_single_shot_fallback(self):
        decision, result, _ = self.run_loop(sample_report(), FakeModel(approve_draft()), None)

        self.assertEqual(decision["decision"], "approve")
        self.assertEqual(result.verdict, "fallback")
        self.assertEqual([e["phase"] for e in result.trace], ["plan", "fallback"])

    def _args(self, **overrides) -> argparse.Namespace:
        base = dict(
            report=str(FIXTURE), ollama_url="http://localhost:11434", model="fake-proposer",
            review_model="fake-reviewer", max_iterations=2, auto_pull=False, log_dir=self.tmp / "logs",
            copy_dir=self.tmp / "evidence", no_copy=False, output=None,
        )
        base.update(overrides)
        return argparse.Namespace(**base)

    def test_run_cloud_deployment_writes_all_sinks_and_the_validation_log(self):
        args = self._args()
        with self.assertLogs("ai_loop", level=logging.INFO) as logs:
            summary = review.run_cloud_deployment(
                args, drafter=drafter_with(FakeModel(approve_draft())), reviewer=FakeReviewer("approved")
            )

        self.assertEqual(summary["decision"]["decision"], "approve")
        self.assertEqual(summary["loop"]["verdict"], "approved")
        self.assertEqual(review.EXIT_CODES[summary["decision"]["decision"]], 0)
        # 1. stdout logger
        self.assertTrue(any("PLAN" in line and "smoke_result=pass" in line for line in logs.output))
        self.assertTrue(any("ADAPT" in line for line in logs.output))
        # 2. JSONL, under the mode's own service name
        jsonl = (args.log_dir / "cloud-deployment.jsonl").read_text(encoding="utf-8").splitlines()
        events = [json.loads(line) for line in jsonl]
        self.assertEqual([e["phase"] for e in events], ["plan", "act", "observe", "adapt"])
        self.assertTrue(all(e["service"] == "cloud-deployment" and e["run_id"] == summary["run_id"] for e in events))
        # 3. markdown transcript
        transcript = Path(summary["loop"]["transcript"])
        self.assertEqual(transcript, args.log_dir / "reports" / "cloud-deployment" / f"{summary['run_id']}.md")
        self.assertIn("## OBSERVE", transcript.read_text(encoding="utf-8"))
        # + the validation log next to the report, stamped like azure_report.py's files
        md = Path(summary["validation_log"]["markdown"])
        self.assertEqual(md, args.copy_dir / "cloud-deployment-20261020T061542Z-review.md")
        text = md.read_text(encoding="utf-8")
        self.assertIn("# Cloud Deployment Report Review — validation log", text)
        self.assertIn("| **approve** | yes | pass | 0 |", text)
        self.assertIn("## Final human release decision", text)
        self.assertIn("- [ ] **Approved**", text)
        self.assertIn("## Code corrections applied to the final draft", text)
        self.assertEqual(summary["code_corrections"], [])
        self.assertIn("| PLAN |", text)
        self.assertIn("| OBSERVE |", text)
        saved = json.loads(Path(summary["validation_log"]["json"]).read_text(encoding="utf-8"))
        self.assertEqual(saved["decision"], summary["decision"])
        self.assertEqual((args.copy_dir / "latest-review.md").read_text(encoding="utf-8"), text)

    def test_refusal_exit_code_and_log(self):
        report = sample_report()
        report["smoke_test"] = {}
        report_path = self.tmp / "latest.json"
        report_path.write_text(json.dumps(report), encoding="utf-8")
        args = self._args(report=str(report_path), review_model="", copy_dir=None)

        summary = review.run_cloud_deployment(args, drafter=drafter_with(FakeModel(approve_draft())))

        self.assertEqual(summary["decision"]["decision"], "insufficient_evidence")
        self.assertEqual(review.EXIT_CODES["insufficient_evidence"], 2)
        log = (self.tmp / "latest-review.md").read_text(encoding="utf-8")  # next to the report by default
        self.assertIn("**insufficient_evidence**", log)
        self.assertIn("smoke_test.result is missing", log)
        self.assertEqual(summary["code_corrections"], ["evidence gaps -> fixed insufficient_evidence decision, no model call"])
        self.assertIn("- evidence gaps -> fixed insufficient_evidence decision, no model call", log)

    def test_main_fails_clearly_without_a_report(self):
        with self.assertRaises(SystemExit) as exit_info:
            review.main(["--report", str(self.tmp / "missing.json")])
        self.assertIn("No report at", str(exit_info.exception))


if __name__ == "__main__":
    unittest.main()

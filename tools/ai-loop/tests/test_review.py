"""Unit tests for the Release 2 review modes.

They use fake evidence and a fake model. Nothing calls Ollama or GitHub.

    python -m unittest discover -s tools/ai-loop/tests
"""

import argparse
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import review  # noqa: E402

WORKFLOW = "aaaaaaaa-0000-0000-0000-000000000000"


def history_event(sequence, status, details=None, run_id="run-1"):
    return {"sequence": sequence, "workflow_id": WORKFLOW, "status": status, "details": details or {},
            "created_at": "2026-10-20T00:00:00+00:00", "task": "What is flowering?", "run_id": run_id}


def write_multi_agent_evidence(directory: Path, *, close=True, reason="Checked the records", reviewer="vgarden-user-1"):
    events = [
        history_event(1, "received", {"source": "vgarden"}),
        history_event(2, "planning", {"run_id": "run-1"}),
        history_event(3, "working"),
        history_event(4, "reviewing"),
        history_event(5, "awaiting_human_review", {"review": {"recommendation": "revise", "issues": ["x"]}}),
        history_event(6, "changes_requested", {"human_review": {"decision": "request_changes",
                                                                "feedback": "Add the count",
                                                                "reviewer_id": "yunus-terminal"}}),
        history_event(7, "planning", {"run_id": "run-2"}, "run-2"),
        history_event(8, "working", run_id="run-2"),
        history_event(9, "reviewing", run_id="run-2"),
        history_event(10, "awaiting_human_review", {"review": {"recommendation": "revise", "issues": ["y"]}}, "run-2"),
    ]
    if close:
        events.append(history_event(11, "accepted", {"human_review": {"decision": "accept", "feedback": reason,
                                                                      "reviewer_id": reviewer}}, "run-2"))
    roles = {"working": "planner", "reviewing": "worker", "awaiting_human_review": "reviewer"}
    audit = [{"sequence": e["sequence"], "workflow_id": WORKFLOW, "event": e["status"],
              "completed_role": roles.get(e["status"]), "model": "qwen3:4b-instruct" if e["status"] in roles else None}
             for e in events]
    (directory / "workflow_history.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
    (directory / "coordination_audit.jsonl").write_text("".join(json.dumps(e) + "\n" for e in audit))
    (directory / "multi-agent-metrics.json").write_text(json.dumps({"tracked_workflows": 1}))


def multi_agent_args(directory, **overrides):
    values = {"mode": "multi-agent", "evidence_dir": str(directory), "source": None}
    values.update(overrides)
    return argparse.Namespace(**values)


def statuses(checks):
    return {c.id: c.status for c in checks}


class MultiAgentChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_complete_workflow_passes_every_check(self):
        write_multi_agent_evidence(self.dir)
        facts, checks, sources = review.gather_multi_agent(multi_agent_args(self.dir))
        self.assertEqual(set(statuses(checks).values()), {"pass"}, checks)
        self.assertEqual(facts["workflows"][0]["runs"], 2)
        self.assertEqual(facts["workflows"][0]["human_decisions"], ["request_changes", "accept"])
        self.assertEqual(len(sources), 3)

    def test_open_workflow_fails_the_closed_check(self):
        write_multi_agent_evidence(self.dir, close=False)
        _, checks, _ = review.gather_multi_agent(multi_agent_args(self.dir))
        self.assertEqual(statuses(checks)["MA-3"], "fail")

    def test_override_without_reason_fails(self):
        write_multi_agent_evidence(self.dir, reason="")
        _, checks, _ = review.gather_multi_agent(multi_agent_args(self.dir))
        self.assertEqual(statuses(checks)["MA-4"], "fail")

    def test_only_terminal_reviews_fail_the_interface_check(self):
        write_multi_agent_evidence(self.dir, reviewer="someone-terminal")
        _, checks, _ = review.gather_multi_agent(multi_agent_args(self.dir))
        self.assertEqual(statuses(checks)["MA-7"], "fail")

    def test_missing_exports_are_reported_as_missing(self):
        _, checks, _ = review.gather_multi_agent(multi_agent_args(self.dir))
        self.assertEqual(statuses(checks), {"MA-1": "missing"})

    def test_source_filter_excludes_other_features(self):
        write_multi_agent_evidence(self.dir)
        _, checks, _ = review.gather_multi_agent(multi_agent_args(self.dir, source="almanac"))
        self.assertEqual(statuses(checks), {"MA-1": "fail"})


class TestingChecks(unittest.TestCase):
    def test_reads_newest_pre_commit_result_per_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            reports = Path(tmp)
            old = {"scan": "tests", "exit_code": 1, "files": ["vgarden/tests"], "stdout": "1 failed",
                   "started_at": "2026-10-20T00:00:00"}
            new = {**old, "exit_code": 0, "stdout": "137 passed in 11s", "started_at": "2026-10-21T00:00:00"}
            (reports / "20261020T000000Z-tests-a.json").write_text(json.dumps(old))
            (reports / "20261021T000000Z-tests-b.json").write_text(json.dumps(new))
            args = argparse.Namespace(security_reports=tmp, services=["vgarden"], workflows=[],
                                      endpoint_workflows=[], ci_evidence=None, repo="o/r", branch="main")
            facts, checks, _ = review.gather_testing(args)
        by_title = {c.title: c for c in checks}
        self.assertEqual(by_title["Pre-commit tests check passes for vgarden"].status, "pass")
        self.assertIn("137 passed", by_title["Pre-commit tests check passes for vgarden"].detail)
        self.assertEqual(by_title["Pre-commit ruff check passes for vgarden"].status, "missing")

    def test_junit_totals_count_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "endpoint.xml").write_text(
                '<testsuites><testsuite tests="2" failures="1" errors="0" skipped="0">'
                '<testcase name="a"/><testcase name="b"/></testsuite></testsuites>')
            totals = review._junit_totals(Path(tmp))
        self.assertEqual((totals["tests"], totals["failures"], totals["testcases"]), (2, 1, ["a", "b"]))


class CloudChecks(unittest.TestCase):
    def test_enabled_ai_service_fails_the_baseline(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "latest.json")
            path.write_text(json.dumps({
                "deployment": {"commit": "abc"}, "endpoints": {"app_url": None},
                "cloud_baseline": {"ai_mode_enabled": False, "mcp_enabled": True},
                "smoke_test": {"result": "pass"},
                "container_apps": [{"name": "proxy", "external": True, "status": "Running"}],
                "postgres": [{"name": "pg", "publicNetworkAccess": "Enabled"}],
            }))
            args = argparse.Namespace(grounding=str(path), url=None, paths=["/"], repo="o/r", branch="main",
                                      workflows=["vgarden.yml"], deploy_workflow="cloud-deployment.yml")
            with mock.patch.object(review, "_get_json", side_effect=review.error.URLError("offline")):
                _, checks, _ = review.gather_cloud(args)
        found = statuses(checks)
        self.assertEqual(found["CD-2"], "fail")
        self.assertEqual(found["CD-3"], "pass")
        self.assertEqual(found["CD-5"], "fail")
        self.assertEqual(found["CD-6"], "missing")  # GitHub offline is never a pass
        self.assertEqual(found["CD-7"], "missing")  # no URL to probe


CHECKS = [review.Check("X-1", "first", "pass", "ok"), review.Check("X-2", "second", "fail", "broken")]


def good_draft(**overrides):
    draft = {"summary": "One check fails.", "verdict": "not_ready", "recommendations": ["Fix X-2."],
             "findings": [{"check_id": "X-2", "severity": "major", "finding": "second is broken"}]}
    draft.update(overrides)
    return draft


class ObserveRules(unittest.TestCase):
    def test_good_draft_has_no_issues(self):
        self.assertEqual(review.rule_issues(good_draft(), CHECKS), [])

    def test_invented_check_id_is_caught(self):
        draft = good_draft(findings=good_draft()["findings"] + [{"check_id": "X-9", "severity": "info", "finding": "?"}])
        self.assertTrue(any("X-9" in issue for issue in review.rule_issues(draft, CHECKS)))

    def test_failed_check_must_be_raised(self):
        issues = review.rule_issues(good_draft(findings=[]), CHECKS)
        self.assertTrue(any("X-2" in issue for issue in issues))

    def test_cannot_call_a_failing_release_ready(self):
        issues = review.rule_issues(good_draft(verdict="ready"), CHECKS)
        self.assertTrue(any("not_ready" in issue for issue in issues))

    def test_deterministic_review_meets_the_rules(self):
        self.assertEqual(review.rule_issues(review.deterministic_review(CHECKS), CHECKS), [])
        passing = [CHECKS[0]]
        self.assertEqual(review.deterministic_review(passing)["verdict"], "ready")


def loop_args(tmp, **overrides):
    values = {"mode": "multi-agent", "log_dir": tmp, "no_model": False, "no_review_model": True,
              "model": "m", "review_model": "m", "ollama_url": "http://ollama.test", "timeout": 5,
              "max_iterations": 2, "decision": "accept", "reason": "ok", "reviewer_id": "tester"}
    values.update(overrides)
    return argparse.Namespace(**values)


class Loop(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        patcher = mock.patch.dict(review.GATHER, {"multi-agent": lambda args: ({"n": 1}, list(CHECKS), ["src"])})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)
        ready = mock.patch.object(review, "ensure_model")
        ready.start()
        self.addCleanup(ready.stop)

    def phases(self, result):
        return [json.loads(line)["phase"] for line in
                Path(self.tmp.name, "review-multi-agent.jsonl").read_text().splitlines()
                if json.loads(line)["run_id"] == result["run_id"]]

    def test_bad_draft_is_revised_with_the_rule_feedback(self):
        drafts = [good_draft(verdict="ready"), good_draft()]
        with mock.patch.object(review, "draft_review", side_effect=drafts) as draft:
            result = review.run_review(loop_args(self.tmp.name))
        self.assertEqual(result["iterations"], 2)
        self.assertEqual(result["review"]["verdict"], "not_ready")
        self.assertIn("not_ready", draft.call_args_list[1].args[2])  # feedback carried into ACT
        self.assertEqual(self.phases(result), ["plan", "act", "observe", "adapt", "act", "observe", "adapt",
                                               "human_review", "result"])
        self.assertEqual(result["human_review"]["decision"], "accept")

    def test_draft_that_never_meets_the_rules_falls_back_to_the_checks(self):
        with mock.patch.object(review, "draft_review", return_value=good_draft(verdict="ready")):
            result = review.run_review(loop_args(self.tmp.name))
        self.assertEqual(result["verdict_source"], "checks_after_capped_model")
        self.assertEqual(result["review"]["verdict"], "not_ready")

    def test_unreachable_model_falls_back_and_is_logged(self):
        with mock.patch.object(review, "draft_review", side_effect=review.LoopError("down")):
            result = review.run_review(loop_args(self.tmp.name))
        self.assertEqual(result["verdict_source"], "checks_only")
        self.assertIn("fallback", self.phases(result))

    def test_second_model_revise_triggers_another_draft(self):
        reviewer = mock.Mock()
        reviewer.review.side_effect = [{"verdict": "revise", "issues": ["count is wrong"], "guidance": "fix"},
                                       {"verdict": "approved", "issues": [], "guidance": ""}]
        with mock.patch.object(review, "Reviewer", return_value=reviewer), \
                mock.patch.object(review, "draft_review", return_value=good_draft()) as draft:
            result = review.run_review(loop_args(self.tmp.name, no_review_model=False))
        self.assertEqual(result["iterations"], 2)
        self.assertIn("count is wrong", draft.call_args_list[1].args[2])
        self.assertEqual(result["verdict_source"], "model")

    def test_no_decision_without_a_terminal_is_pending(self):
        with mock.patch.object(review, "draft_review", return_value=good_draft()), \
                mock.patch.object(review.sys.stdin, "isatty", return_value=False):
            result = review.run_review(loop_args(self.tmp.name, decision=None))
        self.assertEqual(result["human_review"]["decision"], "pending")


if __name__ == "__main__":
    unittest.main()

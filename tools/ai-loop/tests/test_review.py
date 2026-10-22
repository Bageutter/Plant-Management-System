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


EVIDENCE = {"mode": "vgarden-api", "passages": [{"chunk_id": "garden-1-plantings", "title": "t", "text": "Tomato"}]}


def worker(cited=("garden-1-plantings",), insufficient=False):
    return {"evidence": EVIDENCE, "result": {"answer": "Tomato", "cited_chunk_ids": list(cited),
                                             "insufficient_context": insufficient}}


def write_multi_agent_evidence(directory: Path, *, close=True, reason="Checked the records", reviewer="vgarden-user-1",
                               second_worker=None):
    events = [
        history_event(1, "received", {"source": "vgarden"}),
        history_event(2, "planning", {"run_id": "run-1"}),
        history_event(3, "working"),
        history_event(4, "reviewing", worker()),
        history_event(5, "awaiting_human_review", {"review": {"recommendation": "revise", "issues": ["x"]}}),
        history_event(6, "changes_requested", {"human_review": {"decision": "request_changes",
                                                                "feedback": "Add the count",
                                                                "reviewer_id": "yunus-terminal"}}),
        history_event(7, "planning", {"run_id": "run-2"}, "run-2"),
        history_event(8, "working", run_id="run-2"),
        history_event(9, "reviewing", second_worker or worker(), run_id="run-2"),
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
    values = {"mode": "multi-agent", "evidence_dir": str(directory), "source": None,
              "feature_url": None, "multi_agent_url": None}
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

    def test_citation_outside_the_evidence_fails_grounding(self):
        write_multi_agent_evidence(self.dir, second_worker=worker(cited=("garden-9-secret",)))
        facts, checks, _ = review.gather_multi_agent(multi_agent_args(self.dir))
        found = {c.id: c for c in checks}
        self.assertEqual(found["MA-10"].status, "fail")
        self.assertIn("garden-9-secret", found["MA-10"].detail)
        self.assertEqual(found["MA-9"].status, "pass")
        self.assertEqual(facts["grounding"]["worker_runs"], 2)

    def test_answer_without_a_citation_fails_grounding(self):
        write_multi_agent_evidence(self.dir, second_worker=worker(cited=()))
        _, checks, _ = review.gather_multi_agent(multi_agent_args(self.dir))
        self.assertEqual(statuses(checks)["MA-10"], "fail")

    def test_worker_run_without_evidence_fails(self):
        write_multi_agent_evidence(self.dir, second_worker={"result": {"answer": "x", "cited_chunk_ids": [],
                                                                       "insufficient_context": True}})
        _, checks, _ = review.gather_multi_agent(multi_agent_args(self.dir))
        self.assertEqual(statuses(checks)["MA-9"], "fail")

    def test_live_integration_checks(self):
        write_multi_agent_evidence(self.dir)
        replies = {
            "http://feature.test/integrations": {"multi_agent": {"enabled": True, "url": "http://host:8003"}},
            "http://mas.test/healthz": {"service": "multi-agent-server", "status": "ok"},
        }
        args = multi_agent_args(self.dir, feature_url="http://feature.test", multi_agent_url="http://mas.test")
        with mock.patch.object(review, "_get_json", side_effect=lambda url: replies[url]):
            _, checks, sources = review.gather_multi_agent(args)
        self.assertEqual((statuses(checks)["MA-12"], statuses(checks)["MA-13"]), ("pass", "pass"))
        self.assertIn("http://mas.test", sources)

    def test_disabled_feature_fails_and_unreachable_server_is_missing(self):
        write_multi_agent_evidence(self.dir)

        def reply(url):
            if "healthz" in url:
                raise review.error.URLError("refused")
            return {"multi_agent": {"enabled": False, "url": "http://host:8003"}}

        args = multi_agent_args(self.dir, feature_url="http://feature.test", multi_agent_url="http://mas.test")
        with mock.patch.object(review, "_get_json", side_effect=reply):
            _, checks, _ = review.gather_multi_agent(args)
        self.assertEqual((statuses(checks)["MA-12"], statuses(checks)["MA-13"]), ("fail", "missing"))

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
                                      endpoint_workflows=[], ci_evidence=None, repo="o/r", branch="main",
                                      test_evidence=str(Path(tmp) / "none"))
            facts, checks, _ = review.gather_testing(args)
        by_title = {c.title: c for c in checks}
        self.assertEqual(by_title["Pre-commit tests check passes for vgarden"].status, "pass")
        self.assertIn("137 passed", by_title["Pre-commit tests check passes for vgarden"].detail)
        self.assertEqual(by_title["Pre-commit ruff check passes for vgarden"].status, "missing")

    def test_grouped_scan_updates_every_covered_service_and_preserves_failures(self):
        for exit_code, expected in ((0, "pass"), (1, "fail")):
            with self.subTest(exit_code=exit_code), tempfile.TemporaryDirectory() as tmp:
                old = {"scan": "audit", "exit_code": 1, "files": ["health/requirements.txt"],
                       "stdout": '{"dependencies": []}', "started_at": "2026-10-20T00:00:00"}
                grouped = {**old, "exit_code": exit_code,
                           "files": ["almanac/requirements-dev.txt", "health/requirements-dev.txt",
                                     "ai-services/rag-server/requirements.txt"],
                           "started_at": "2026-10-21T00:00:00"}
                Path(tmp, "20261020-audit-old.json").write_text(json.dumps(old))
                Path(tmp, "20261021-audit-new.json").write_text(json.dumps(grouped))
                args = argparse.Namespace(security_reports=tmp,
                                          services=["almanac", "health", "ai-services/rag-server", "auth"],
                                          workflows=[], endpoint_workflows=[], ci_evidence=None,
                                          repo="o/r", branch="main", test_evidence=str(Path(tmp) / "none"))
                _, checks, _ = review.gather_testing(args)
                by_title = {c.title: c for c in checks}
                for service in args.services[:3]:
                    check = by_title[f"Pre-commit audit check passes for {service}"]
                    self.assertEqual(check.status, expected)
                    self.assertIn("combined scan", check.detail)
                    self.assertIn("2026-10-21", check.detail)
                self.assertEqual(by_title["Pre-commit audit check passes for auth"].status, "missing")

    def test_junit_totals_count_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "endpoint.xml").write_text(
                '<testsuites><testsuite tests="2" failures="1" errors="0" skipped="0">'
                '<testcase name="a"/><testcase name="b"/></testsuite></testsuites>')
            totals = review._junit_totals(Path(tmp))
        self.assertEqual((totals["tests"], totals["failures"], totals["testcases"]), (2, 1, ["a", "b"]))


def write_service_evidence(root: Path, *, exit_code=0, failures=0, untested=1):
    folder = root / "vgarden"
    folder.mkdir(parents=True)
    routes = [{"methods": ["GET"], "path": f"/r{i}", "file": "vgarden/routes.py", "line": i, "tested": i >= untested}
              for i in range(3)]
    (folder / "routes.json").write_text(json.dumps({
        "service": "vgarden", "commit": "abc1234", "exit_code": exit_code, "line_coverage_percent": 90.0,
        "endpoints": 3, "endpoints_tested": sum(r["tested"] for r in routes), "routes": routes}))
    (folder / "junit.xml").write_text(
        f'<testsuites><testsuite tests="5" failures="{failures}" errors="0" skipped="1">'
        '<testcase name="a"/></testsuite></testsuites>')
    log = ("FAILED tests/test_x.py::test_broken - AssertionError\n" if failures else "") + "4 passed, 2 warnings in 1s\n"
    (folder / "pytest.txt").write_text(log)


class TestEvidenceChecks(unittest.TestCase):
    def gather(self, tmp):
        args = argparse.Namespace(security_reports=str(Path(tmp) / "none"), services=["vgarden"], workflows=[],
                                  endpoint_workflows=[], ci_evidence=None, repo="o/r", branch="main",
                                  test_evidence=tmp)
        return review.gather_testing(args)

    def test_untested_endpoints_warn_and_are_listed(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_service_evidence(Path(tmp))
            facts, checks, _ = self.gather(tmp)
        by_title = {c.title: c for c in checks}
        self.assertEqual(by_title["vgarden tests pass"].status, "pass")
        self.assertIn("2 warnings", by_title["vgarden tests pass"].detail)
        coverage = by_title["Every vgarden endpoint is exercised by a test"]
        self.assertEqual(coverage.status, "warn")
        self.assertIn("GET /r0", coverage.detail)
        self.assertEqual(facts["test_evidence"][0]["untested_endpoints"], ["GET /r0 (vgarden/routes.py:0)"])

    def test_failing_tests_fail_and_name_the_test(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_service_evidence(Path(tmp), exit_code=1, failures=1, untested=0)
            _, checks, _ = self.gather(tmp)
        by_title = {c.title: c for c in checks}
        self.assertEqual(by_title["vgarden tests pass"].status, "fail")
        self.assertIn("test_broken", by_title["vgarden tests pass"].detail)
        self.assertEqual(by_title["Every vgarden endpoint is exercised by a test"].status, "pass")

    def test_missing_evidence_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, checks, _ = self.gather(tmp)
        self.assertEqual({c.status for c in checks if "vgarden" in c.title}, {"missing"})


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
        self.assertEqual(found["CD-CRUD"], "missing")

    def test_cloud_review_requires_crud_success_from_the_deployed_run(self):
        for result, commit, expected in (("pass", "abc", "pass"), ("fail", "abc", "fail"),
                                          ("pass", "old", "fail")):
            with self.subTest(result=result, commit=commit), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp, "latest.json")
                path.write_text(json.dumps({
                    "deployment": {"commit": "abc", "workflow_run_url": "run-42"},
                    "endpoints": {"app_url": "https://cloud.invalid"},
                    "crud_test": {"result": result, "commit": commit,
                                  "workflow_run_url": "run-42", "target": "https://cloud.invalid"},
                }))
                args = argparse.Namespace(grounding=str(path), url=None, paths=[], repo="o/r", branch="main",
                                          workflows=["vgarden.yml"], deploy_workflow="cloud-deployment.yml")
                with mock.patch.object(review, "_get_json", side_effect=review.error.URLError("offline")):
                    facts, checks, _ = review.gather_cloud(args)
                self.assertEqual(statuses(checks)["CD-CRUD"], expected)
                self.assertEqual(facts["deployment"]["crud_test"]["commit"], commit)


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

    def test_warn_needs_a_finding_and_blocks_ready(self):
        checks = [review.Check("X-1", "first", "pass", "ok"), review.Check("X-3", "coverage", "warn", "gaps")]
        draft = {"summary": "Coverage gaps.", "verdict": "ready", "recommendations": [], "findings": []}
        issues = review.rule_issues(draft, checks)
        self.assertTrue(any("X-3 warns" in issue for issue in issues))
        self.assertTrue(any("ready_with_fixes" in issue for issue in issues))
        fixed = {**draft, "verdict": "ready_with_fixes",
                 "findings": [{"check_id": "X-3", "severity": "minor", "finding": "gaps"}]}
        self.assertEqual(review.rule_issues(fixed, checks), [])
        self.assertEqual(review.deterministic_review(checks)["verdict"], "ready_with_fixes")

    def test_deterministic_review_meets_the_rules(self):
        self.assertEqual(review.rule_issues(review.deterministic_review(CHECKS), CHECKS), [])
        passing = [CHECKS[0]]
        self.assertEqual(review.deterministic_review(passing)["verdict"], "ready")


def loop_args(tmp, **overrides):
    values = {"mode": "multi-agent", "log_dir": tmp, "no_model": False, "no_review_model": True,
              "model": "m", "review_model": "m", "ollama_url": "http://ollama.test", "timeout": 5,
              "max_iterations": 2, "decision": "accept", "reason": "ok", "reviewer_id": "tester",
              "num_ctx": 8192, "report": None}
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

    def test_writes_the_markdown_report(self):
        report = Path(self.tmp.name, "report.md")
        with mock.patch.object(review, "draft_review", return_value=good_draft()):
            result = review.run_review(loop_args(self.tmp.name, report=str(report)))
        text = report.read_text()
        self.assertIn("| X-2 | second | ❌ fail | broken |", text)
        self.assertIn("Decision: **accept**", text)
        self.assertIn(result["run_id"], text)

    def test_second_review_failure_keeps_a_draft_that_met_the_rules(self):
        reviewer = mock.Mock()
        reviewer.review.side_effect = review.LoopError("truncated JSON")
        with mock.patch.object(review, "Reviewer", return_value=reviewer), \
                mock.patch.object(review, "draft_review", return_value=good_draft()):
            result = review.run_review(loop_args(self.tmp.name, no_review_model=False))
        self.assertEqual(result["verdict_source"], "model_rules_only")
        self.assertEqual(result["review"], good_draft())
        self.assertEqual(result["iterations"], 1)

    def test_no_decision_without_a_terminal_is_pending(self):
        with mock.patch.object(review, "draft_review", return_value=good_draft()), \
                mock.patch.object(review.sys.stdin, "isatty", return_value=False):
            result = review.run_review(loop_args(self.tmp.name, decision=None))
        self.assertEqual(result["human_review"]["decision"], "pending")


if __name__ == "__main__":
    unittest.main()


class CollectorEndpoints(unittest.TestCase):
    """scripts/test/collect-test-evidence.py finds endpoints without importing the app."""

    def test_finds_routes_and_tools(self):
        import importlib.util

        path = Path(__file__).resolve().parents[3] / "scripts" / "test" / "collect-test-evidence.py"
        spec = importlib.util.spec_from_file_location("collect_test_evidence", path)
        collector = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(collector)
        with tempfile.TemporaryDirectory() as tmp:
            service = Path(tmp, "svc")
            (service / "tests").mkdir(parents=True)
            (service / "routes.py").write_text(
                '@bp.route("/items/<int:item_id>", methods=["GET", "POST"])\n'
                'def item(item_id):\n    """Doc."""\n    return "ok"\n\n'
                '@app.get("/healthz")\ndef healthz():\n    return {}\n\n'
                '@server.tool()\ndef search(query):\n    return []\n\n'
                'def helper():\n    return 1\n')
            (service / "tests" / "test_x.py").write_text('@bp.route("/not-an-endpoint")\ndef t():\n    pass\n')
            with mock.patch.object(collector, "ROOT", Path(tmp)):
                found = collector.endpoints("svc")
        summary = [(e["kind"], e["path"], e["methods"], e["body_lines"]) for e in found]
        self.assertEqual(summary, [
            ("http", "/items/<int:item_id>", ["GET", "POST"], [4, 4]),  # docstring skipped
            ("http", "/healthz", ["GET"], [8, 8]),
            ("mcp_tool", "search", [], [12, 12]),
        ])

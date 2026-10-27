"""Release 2 review modes for the shared agentic loop.

``validate.py --mode multi-agent|testing|cloud-deployment`` lands here. The
Release 1 ``mcp`` and ``rag`` modes are unchanged. Each mode reviews an evidence
report and writes a review/validation log:

  PLAN     collect the evidence and run fixed checks on it (no model involved)
  ACT      the local Ollama model drafts a review, given only those facts
  OBSERVE  rule checks (it cites only real checks, raises every failed check,
           and doesn't call a failing release ready), then an independent
           review by a second model through shared/ai_loop.Reviewer
  ADAPT    revise with that feedback, up to --max-iterations, or stop
  HUMAN    a person records the final decision

The log goes to the same three places as every other loop run: stdout,
``logs/review-<mode>.jsonl`` and ``logs/reports/review-<mode>/<run_id>.md``.
Nothing here writes to a service, a database or GitHub; it only reads evidence.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import uuid
import xml.etree.ElementTree as ET  # noqa: S405 -- parses our own CI JUnit files
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib import error, request

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "shared"))
from ai_loop import LoopError, LoopLogger, Reviewer, ensure_model  # noqa: E402

MODES = ("multi-agent", "testing", "cloud-deployment")
DECISIONS = {
    "multi-agent": ("accept", "partially_accept", "reject"),
    "testing": ("accept", "partially_accept", "reject"),
    "cloud-deployment": ("release", "hold", "rollback"),
}
VERDICTS = ("ready", "ready_with_fixes", "not_ready")
SEVERITIES = ("info", "minor", "major", "blocker")
FINAL_DECISIONS = {"accepted", "partially_accepted", "rejected"}
STAGE_ORDER = ("planning", "working", "reviewing", "awaiting_human_review")

REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "check_id": {"type": "string"},
                    "severity": {"type": "string", "enum": list(SEVERITIES)},
                    "finding": {"type": "string"},
                },
                "required": ["check_id", "severity", "finding"],
            },
        },
        "recommendations": {"type": "array", "items": {"type": "string"}},
        "verdict": {"type": "string", "enum": list(VERDICTS)},
    },
    "required": ["summary", "findings", "recommendations", "verdict"],
}

DRAFT_PROMPT = """You review {subject} for a university software release.
EVIDENCE is the complete set of facts you may use: a list of checks (each with an
id, a status of pass, warn, fail or missing, and a detail) plus extra facts.

Write a short, specific review:
- summary: two or three sentences on what the evidence shows.
- findings: one entry for every check whose status is fail or missing (severity
  major or blocker), one for every warn check (severity minor or higher), plus any
  other notable point (info). Use the exact check_id from EVIDENCE. Never invent a
  check id, number, name or date.
- recommendations: concrete next steps, each tied to the evidence.
- verdict: "ready" only when every check passes; "ready_with_fixes" when nothing
  fails or is missing but some checks warn; otherwise "not_ready".
If the evidence cannot support a statement, leave it out rather than guess.
Return JSON only."""

OBSERVE_PROMPT = """You are an independent reviewer of a DRAFT release review.
GROUNDING holds the only facts the draft may use: checks with statuses and details,
plus extra facts. Restating or summarising those values is correct, not an error.

Return "revise" only when one of these is clearly true:
- The draft states a number, name, date or outcome that is absent from, or
  contradicts, the grounding.
- The draft calls something passing that the grounding marks warn, fail or missing.
- A recommendation has no basis in the grounding.
Otherwise return "approved". When genuinely unsure, return "approved".

Return JSON only, exactly these keys:
{
  "verdict": "approved" or "revise",
  "issues": ["short, specific problem", ...],
  "guidance": "one concrete instruction for the next draft"
}"""

SUBJECTS = {
    "multi-agent": "Multi-Agent workflow evidence (Planner -> Worker -> Reviewer -> Human Review)",
    "testing": "pre-commit security scan results and post-commit CI/CD test results",
    "cloud-deployment": "cloud deployment and validation evidence, to support the release decision",
}


@dataclass
class Check:
    id: str
    title: str
    status: str  # pass | warn (needs work, not a blocker) | fail | missing
    detail: str


def _check(checks, cid, title, ok, detail, missing=False, warn=False):
    status = "missing" if missing else "pass" if ok else "warn" if warn else "fail"
    checks.append(Check(cid, title, status, detail))


BLOCKING = ("fail", "missing")
HOOK_TESTED = ("almanac", "health", "vgarden", "auth")


def _rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def _get_json(url: str, timeout: int = 20):
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"Only http(s) URLs are allowed: {url}")
    headers = {"Accept": "application/json", "User-Agent": "ai-loop-review"}
    token = os.environ.get("GITHUB_TOKEN")
    if token and url.startswith("https://api.github.com/"):
        # Optional: 5,000 requests an hour instead of 60 unauthenticated. Only sent to GitHub.
        headers["Authorization"] = f"Bearer {token}"
    req = request.Request(url, headers=headers)  # noqa: S310 -- scheme checked above
    with request.urlopen(req, timeout=timeout) as response:  # noqa: S310 -- scheme checked above
        return json.loads(response.read().decode("utf-8"))


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# --------------------------------------------------------------------------- #
# PLAN: evidence and fixed checks for each mode                               #
# --------------------------------------------------------------------------- #


def gather_multi_agent(args) -> tuple[dict, list[Check], list[str]]:
    directory = Path(args.evidence_dir)
    history_path = directory / "workflow_history.jsonl"
    audit_path = directory / "coordination_audit.jsonl"
    metrics_path = directory / "multi-agent-metrics.json"
    checks: list[Check] = []
    sources = [_rel(p) for p in (history_path, audit_path, metrics_path) if p.exists()]
    if not history_path.exists() or not audit_path.exists():
        _check(checks, "MA-1", "Workflow history and coordination audit exports exist", False,
               f"Expected {_rel(history_path)} and {_rel(audit_path)} (run audit.py in the "
               "Multi-Agent Server first).", missing=True)
        return {"evidence_dir": _rel(directory)}, checks, sources

    history = _read_jsonl(history_path)
    audit = _read_jsonl(audit_path)
    workflows: dict[str, dict] = {}
    for event in history:
        wf = workflows.setdefault(event["workflow_id"], {
            "id": event["workflow_id"][:8], "task": event.get("task"), "source": None,
            "events": [], "reviews": [], "humans": [], "runs": []})
        if event["status"] == "received":
            wf["source"] = (event.get("details") or {}).get("source", "almanac")
        wf["events"].append(event["status"])
        details = event.get("details") or {}
        if event["status"] == "planning":
            wf["runs"].append(details.get("run_id"))
        if event["status"] == "awaiting_human_review" and "review" in details:
            wf["reviews"].append((details["review"] or {}).get("recommendation"))
        if "human_review" in details:
            wf["humans"].append(details["human_review"])
    if args.source:
        workflows = {k: v for k, v in workflows.items() if v["source"] == args.source}
    _check(checks, "MA-1", "Workflow history and coordination audit exports exist", bool(workflows),
           f"{len(history)} history events and {len(audit)} audit events; {len(workflows)} workflows"
           + (f" with source={args.source}" if args.source else "") + ".")
    if not workflows:
        return {"evidence_dir": _rel(directory)}, checks, sources

    # Each run must pass through every stage, in order, before the human review.
    broken = []
    for wf in workflows.values():
        stages = [s for s in wf["events"] if s in STAGE_ORDER]
        expected = list(STAGE_ORDER) * len(wf["runs"])
        if stages[: len(expected)] != expected:
            broken.append(wf["id"])
    total_runs = sum(len(w["runs"]) for w in workflows.values())
    _check(checks, "MA-2", "Every run went Planner -> Worker -> Reviewer -> human review in order",
           not broken, f"{total_runs} runs checked" + (f"; out of order: {', '.join(broken)}" if broken else "."))

    open_ids = [w["id"] for w in workflows.values() if w["events"][-1] not in FINAL_DECISIONS]
    _check(checks, "MA-3", "Every workflow was closed by a human decision", not open_ids,
           "All closed." if not open_ids else f"Still open: {', '.join(open_ids)}.")

    overrides, unexplained = 0, []
    for wf in workflows.values():
        for human, review in zip(wf["humans"], wf["reviews"]):
            if human.get("decision") == "accept" and review and review != "accept":
                overrides += 1
                if not str(human.get("feedback") or "").strip():
                    unexplained.append(wf["id"])
    _check(checks, "MA-4", "Accepting against the Reviewer's advice always has a written reason",
           not unexplained, f"{overrides} overrides" + (f"; no reason given in {', '.join(unexplained)}"
                                                        if unexplained else ", all with a reason."))

    requested, rerun_missing = 0, []
    for wf in workflows.values():
        for index, status in enumerate(wf["events"]):
            if status == "changes_requested":
                requested += 1
                if "planning" not in wf["events"][index + 1:]:
                    rerun_missing.append(wf["id"])
    _check(checks, "MA-5", "Every 'request changes' started a revised run", not rerun_missing,
           f"{requested} change requests" + (f"; no rerun in {', '.join(rerun_missing)}"
                                              if rerun_missing else ", each followed by a new run."))

    handoffs = [e for e in audit if e.get("completed_role")]
    no_model = [e["sequence"] for e in handoffs if not e.get("model")]
    _check(checks, "MA-6", "Every agent handoff in the audit names the model that did it", not no_model,
           f"{len(handoffs)} handoffs" + (f"; no model at sequence {no_model[:5]}" if no_model else "."))

    reviewers = sorted({str(h.get("reviewer_id")) for w in workflows.values() for h in w["humans"]})
    # Terminal runs name themselves "...terminal"; UI decisions carry the signed-in or
    # web user ("vgarden-user-1", "health-user-web", almanac's "user:<id>").
    terminal = [r for r in reviewers if "terminal" in r]
    ui = [r for r in reviewers if "terminal" not in r]
    _check(checks, "MA-7", "Human reviews came from both the frontend UI and the terminal",
           bool(ui and terminal), f"UI reviewer ids: {ui or 'none'}; terminal reviewer ids: {terminal or 'none'}.")

    metrics = json.loads(metrics_path.read_text()) if metrics_path.exists() else None
    if metrics is None:
        _check(checks, "MA-8", "Metrics export matches the history", False,
               f"{_rel(metrics_path)} not found (GET /workflow/metrics).", missing=True)
    elif args.source:
        checks.append(Check("MA-8", "Metrics export matches the history", "pass",
                            "Not compared: metrics cover every source, this review is filtered."))
    else:
        tracked = metrics.get("tracked_workflows")
        _check(checks, "MA-8", "Metrics export matches the history", tracked == len(workflows),
               f"metrics tracked_workflows={tracked}, history has {len(workflows)}.")

    # Grounding: what each Worker run was given, and what it cited.
    runs = [e for e in history if e["workflow_id"] in workflows and e["status"] == "reviewing"]
    ungrounded, uncited, outside, given = [], [], [], 0
    for event in runs:
        details = event.get("details") or {}
        passages = (details.get("evidence") or {}).get("passages") or []
        result = details.get("result") or {}
        ids = {p.get("chunk_id") for p in passages}
        cited = set(result.get("cited_chunk_ids") or [])
        given += len(passages)
        label = f"{event['workflow_id'][:8]}#{event['sequence']}"
        if not passages:
            ungrounded.append(label)
        if result.get("insufficient_context") is False and not cited:
            uncited.append(label)
        if cited - ids:
            outside.append(f"{label} cited {sorted(cited - ids)}")
    _check(checks, "MA-9", "Every Worker run was given evidence passages", bool(runs) and not ungrounded,
           f"{len(runs)} Worker runs, {given} passages in total"
           + (f"; no evidence: {', '.join(ungrounded)}" if ungrounded else "."))
    _check(checks, "MA-10", "Workers cite only passages they were given, and every answer cites one",
           bool(runs) and not uncited and not outside,
           "; ".join(filter(None, [f"answers without a citation: {', '.join(uncited)}" if uncited else "",
                                   f"citations outside the evidence: {'; '.join(outside)}" if outside else ""]))
           or f"All {len(runs)} answers cite only their own evidence.")
    reviewed = [e for e in history if e["workflow_id"] in workflows and e["status"] == "awaiting_human_review"]
    verdicts = [((e.get("details") or {}).get("review") or {}).get("recommendation") for e in reviewed]
    _check(checks, "MA-11", "The Reviewer gave a verdict on every Worker answer",
           len(reviewed) == len(runs) and all(verdicts),
           f"{len(reviewed)} reviews for {len(runs)} answers; verdicts: "
           + ", ".join(f"{v}={verdicts.count(v)}" for v in sorted(set(map(str, verdicts)))) + ".")

    # The feature's live integration with the server.
    feature, server = None, None
    if getattr(args, "feature_url", None):
        try:
            feature = (_get_json(f"{args.feature_url.rstrip('/')}/integrations") or {}).get("multi_agent")
        except (error.URLError, TimeoutError, ValueError, OSError) as exc:
            feature = {"error": str(exc)}
        ok = isinstance(feature, dict) and feature.get("enabled") is True and bool(feature.get("url"))
        _check(checks, "MA-12", "The feature is configured to use the Multi-Agent Server", ok,
               f"{args.feature_url}/integrations multi_agent: {feature}",
               missing=isinstance(feature, dict) and "error" in feature)
    if getattr(args, "multi_agent_url", None):
        try:
            server = _get_json(f"{args.multi_agent_url.rstrip('/')}/healthz")
        except (error.URLError, TimeoutError, ValueError, OSError) as exc:
            server = {"error": str(exc)}
        _check(checks, "MA-13", "The Multi-Agent Server answers its health check",
               isinstance(server, dict) and server.get("status") == "ok",
               f"{args.multi_agent_url}/healthz: {server}", missing="error" in (server or {}))
    if feature is not None or server is not None:
        sources += [u for u in (getattr(args, "feature_url", None), getattr(args, "multi_agent_url", None)) if u]

    facts = {
        "workflows": [
            {"id": w["id"], "source": w["source"], "task": w["task"], "runs": len(w["runs"]),
             "reviewer_recommendations": w["reviews"],
             "human_decisions": [h.get("decision") for h in w["humans"]],
             "final_status": w["events"][-1]}
            for w in workflows.values()
        ],
        "grounding": {"worker_runs": len(runs), "passages_given": given,
                      "answers_citing_only_their_evidence": len(runs) - len(outside)},
        "integration": {"feature": feature, "server": server},
    }
    if metrics and not args.source:  # server-wide numbers would misdescribe one feature's workflows
        facts["metrics"] = {k: (metrics[k]["value"] if isinstance(metrics.get(k), dict) and "value" in metrics[k]
                                else metrics.get(k))
                            for k in ("handoff_success_rate", "plan_generation_rate", "worker_completion_rate",
                                      "workflow_completion_rate", "human_approval_rate", "rework_ratio",
                                      "run_attempts", "human_requested_revision_runs")}
        facts["metrics"]["reviewer_issues_reported"] = (metrics.get("reviewer_defect_yield") or {}).get("issues_reported")
    return facts, checks, sources


def _report_services(report: dict) -> set[str]:
    services = set()
    for name in report.get("files") or []:
        for service in ("vgarden", "auth", "almanac", "health", "shared/frontend", "ai-services/mcp-server",
                        "ai-services/rag-server", "ai-services/multi-agent-server"):
            if name == service or name.startswith(service + "/"):
                services.add(service)
    return services


def _scan_summary(report: dict) -> str:
    stdout = report.get("stdout") or ""
    if report["scan"] == "ruff":
        return f"{len(json.loads(stdout or '[]'))} Ruff security findings"
    if report["scan"] == "audit":
        deps = json.loads(stdout or "{}").get("dependencies", [])
        return f"{len(deps)} packages, {sum(1 for d in deps if d.get('vulns'))} with known vulnerabilities"
    if report["scan"] == "tests":
        lines = [line for line in stdout.splitlines() if re.search(r"\d+ (passed|failed|errors?)", line)]
        return lines[-1].strip() if lines else "no pytest summary"
    return "no new secrets" if report["exit_code"] == 0 else "possible secrets flagged"


def _junit_totals(directory: Path) -> dict:
    totals = {"files": 0, "tests": 0, "failures": 0, "errors": 0, "skipped": 0, "testcases": []}
    for path in sorted(directory.rglob("*.xml")):
        root = ET.parse(path).getroot()  # noqa: S314 -- our own CI JUnit output
        suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
        totals["files"] += 1
        for suite in suites:
            for key in ("tests", "failures", "errors", "skipped"):
                totals[key] += int(suite.get(key, 0))
            totals["testcases"] += [case.get("name") for case in suite.iter("testcase")][:20]
    return totals


def gather_testing(args) -> tuple[dict, list[Check], list[str]]:
    checks: list[Check] = []
    sources: list[str] = []
    facts: dict = {"pre_commit": [], "ci": [], "junit": None}

    # Pre-commit: the newest saved result of each check for each service.
    reports_dir = Path(args.security_reports)
    latest: dict[tuple[str, str], dict] = {}
    for path in sorted(reports_dir.glob("*.json")) if reports_dir.exists() else []:
        report = json.loads(path.read_text())
        services = _report_services(report)
        if report.get("scan") in ("ruff", "secrets", "audit", "tests"):
            for service in services.intersection(args.services):
                latest[(service, report["scan"])] = {**report, "_path": path}
    number = 0
    for service in args.services:
        # The hook runs pytest only for the four feature services
        # (scripts/security/run_checks.py); the others' tests are in the test evidence below.
        scans = ("ruff", "secrets", "audit", "tests") if service in HOOK_TESTED else ("ruff", "secrets", "audit")
        for scan in scans:
            number += 1
            cid, title = f"TS-{number}", f"Pre-commit {scan} check passes for {service}"
            report = latest.get((service, scan))
            if report is None:
                _check(checks, cid, title, False, f"No saved {scan} result for {service} in {_rel(reports_dir)}.",
                       missing=True)
                continue
            sources.append(_rel(report["_path"]))
            summary = _scan_summary(report)
            covered = sorted(_report_services(report))
            if len(covered) > 1:
                summary += f" (combined scan: {', '.join(covered)}; result applies to the whole scan)"
            _check(checks, cid, title, report["exit_code"] == 0,
                   f"{summary} ({report['started_at'][:16]}, trigger {report.get('trigger', 'hook')}).")
            facts["pre_commit"].append({"service": service, "check": scan, "result": checks[-1].status,
                                        "summary": summary, "at": report["started_at"][:16]})

    # Post-commit CI: the newest finished run of each workflow on the branch.
    api = f"https://api.github.com/repos/{args.repo}"
    for workflow in args.workflows:
        number += 1
        cid, title = f"TS-{number}", f"Latest {workflow} run on {args.branch} succeeded"
        try:
            runs = _get_json(f"{api}/actions/workflows/{workflow}/runs?branch={args.branch}&per_page=10")["workflow_runs"]
        except (error.URLError, TimeoutError, ValueError, KeyError) as exc:
            _check(checks, cid, title, False, f"GitHub API unavailable: {exc}", missing=True)
            continue
        finished = [r for r in runs if r["status"] == "completed" and r["conclusion"] != "cancelled"]
        if not finished:
            _check(checks, cid, title, False, f"No finished {workflow} run on {args.branch}.", missing=True)
            continue
        run = finished[0]
        jobs = _get_json(f"{api}/actions/runs/{run['id']}/jobs").get("jobs", [])
        sources.append(run["html_url"])
        _check(checks, cid, title, run["conclusion"] == "success",
               f"run {run['id']} on {run['head_sha'][:7]} ({run['event']}): {run['conclusion']}; jobs: "
               + ", ".join(f"{j['name']}={j['conclusion']}" for j in jobs))
        entry = {"workflow": workflow, "run_id": run["id"], "commit": run["head_sha"][:7],
                 "conclusion": run["conclusion"], "url": run["html_url"],
                 "jobs": {j["name"]: j["conclusion"] for j in jobs}}
        steps = [s for j in jobs for s in j.get("steps", []) if "endpoint" in s["name"].lower()]
        if workflow in args.endpoint_workflows:
            number += 1
            _check(checks, f"TS-{number}", f"{workflow} ran the assigned endpoint tests", bool(steps)
                   and all(s["conclusion"] == "success" for s in steps),
                   "; ".join(f"'{s['name']}'={s['conclusion']}" for s in steps) or "No endpoint test step found.")
            entry["endpoint_steps"] = {s["name"]: s["conclusion"] for s in steps}
        facts["ci"].append(entry)

    # Each service's own test results, log and endpoint coverage
    # (scripts/test/collect-test-evidence.py).
    evidence_dir = Path(args.test_evidence)
    facts["test_evidence"] = []
    for service in args.services:
        name = service.rsplit("/", 1)[-1]
        folder = evidence_dir / name
        summary_path = folder / "routes.json"
        number += 1
        tests_id = f"TS-{number}"
        number += 1
        cover_id = f"TS-{number}"
        if not summary_path.exists():
            for cid, title in ((tests_id, f"{service} tests pass"), (cover_id, f"Every {service} endpoint is exercised by a test")):
                _check(checks, cid, title, False, f"No saved test evidence in {_rel(folder)} "
                       "(run scripts/test/collect-test-evidence.py).", missing=True)
            continue
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        sources.append(_rel(folder))
        log = (folder / "pytest.txt").read_text(encoding="utf-8") if (folder / "pytest.txt").exists() else ""
        warnings = re.search(r"(\d+) warnings?", log.splitlines()[-1] if log.strip() else "")
        totals = _junit_totals(folder) if (folder / "junit.xml").exists() else None
        if summary.get("exit_code") is None:
            _check(checks, tests_id, f"{service} tests pass", False, "The service has no tests.", warn=True)
        else:
            bad = (totals["failures"] + totals["errors"]) if totals else None
            failing = re.findall(r"^FAILED (\S+)", log, re.MULTILINE)[:5]
            _check(checks, tests_id, f"{service} tests pass", summary["exit_code"] == 0 and bad == 0,
                   (f"{totals['tests']} tests: {totals['failures']} failures, {totals['errors']} errors, "
                    f"{totals['skipped']} skipped" if totals else "no JUnit file")
                   + (f"; {warnings.group(1)} warnings in the log" if warnings else "")
                   + (f"; failing: {', '.join(failing)}" if failing else "")
                   + f" (commit {summary.get('commit')}).")
        untested = [r for r in summary["routes"] if not r["tested"]]
        listed = ", ".join(f"{'/'.join(r['methods']) or 'tool'} {r['path']}" for r in untested[:8])
        _check(checks, cover_id, f"Every {service} endpoint is exercised by a test", not untested,
               f"{summary['endpoints_tested']}/{summary['endpoints']} endpoints run by the tests"
               + (f"; not exercised: {listed}" + (f" and {len(untested) - 8} more" if len(untested) > 8 else "")
                  + "." if untested else ".") + f" Line coverage {summary.get('line_coverage_percent')}%.",
               warn=True)
        facts["test_evidence"].append({
            "service": service, "commit": summary.get("commit"),
            "tests": totals["tests"] if totals else 0, "failures": totals["failures"] if totals else 0,
            "errors": totals["errors"] if totals else 0, "skipped": totals["skipped"] if totals else 0,
            "warnings": int(warnings.group(1)) if warnings else 0,
            "line_coverage_percent": summary.get("line_coverage_percent"),
            "endpoints": summary["endpoints"], "endpoints_tested": summary["endpoints_tested"],
            "untested_endpoints": [f"{'/'.join(r['methods']) or 'tool'} {r['path']} ({r['file']}:{r['line']})"
                                   for r in untested],
        })

    if args.ci_evidence:
        number += 1
        directory = Path(args.ci_evidence)
        totals = _junit_totals(directory) if directory.exists() else None
        if not totals or not totals["files"]:
            _check(checks, f"TS-{number}", "Downloaded CI JUnit results have no failures", False,
                   f"No JUnit XML under {_rel(directory)}.", missing=True)
        else:
            sources.append(_rel(directory))
            bad = totals["failures"] + totals["errors"]
            _check(checks, f"TS-{number}", "Downloaded CI JUnit results have no failures", bad == 0,
                   f"{totals['tests']} tests in {totals['files']} files: {totals['failures']} failures, "
                   f"{totals['errors']} errors, {totals['skipped']} skipped.")
            facts["junit"] = totals
    return facts, checks, sources


def _probe(url: str, timeout: int = 20) -> tuple[int | None, float, str]:
    started = time.monotonic()
    if not url.startswith(("http://", "https://")):
        return None, 0.0, "not an http(s) URL"
    try:
        req = request.Request(url, headers={"User-Agent": "ai-loop-review"})  # noqa: S310 -- scheme checked above
        with request.urlopen(req, timeout=timeout) as response:  # noqa: S310 -- scheme checked above
            body = response.read(4000).decode("utf-8", "replace")
            return response.status, time.monotonic() - started, body
    except error.HTTPError as exc:
        return exc.code, time.monotonic() - started, ""
    except (error.URLError, TimeoutError, OSError) as exc:
        return None, time.monotonic() - started, str(exc)


def gather_cloud(args) -> tuple[dict, list[Check], list[str]]:
    """Reads the deployment report JSON from scripts/deploy/azure-report.sh, probes
    the live site, and checks the deploy workflow."""
    checks: list[Check] = []
    sources: list[str] = []
    facts: dict = {"url": args.url, "probes": [], "deploy_run": None, "deployment": None}

    grounding_path = Path(args.grounding)
    report = json.loads(grounding_path.read_text(encoding="utf-8")) if grounding_path.exists() else None
    _check(checks, "CD-1", "The deployment report JSON exists", report is not None,
           _rel(grounding_path) if report else f"{_rel(grounding_path)} not found (written by "
           "scripts/deploy/azure-report.sh).", missing=report is None)
    if report:
        sources.append(_rel(grounding_path))
        deployment = report.get("deployment") or {}
        baseline = report.get("cloud_baseline") or {}
        apps = report.get("container_apps") or []
        postgres = report.get("postgres") or []
        facts["deployment"] = {
            "generated_at": report.get("generated_at"), **{k: deployment.get(k) for k in (
                "platform", "resource_group", "location", "commit", "branch", "image_tag", "workflow_run_url")},
            "app_url": (report.get("endpoints") or {}).get("app_url"),
            "cloud_baseline": baseline, "smoke_test": (report.get("smoke_test") or {}).get("result"),
            "container_apps": [{k: a.get(k) for k in ("name", "external", "status", "revision")} for a in apps],
            "postgres": [{k: d.get(k) for k in ("name", "version", "publicNetworkAccess", "backupRetentionDays")}
                         for d in postgres],
            "security_controls": [c.get("control") for c in report.get("security_controls") or []],
        }
        args.url = args.url or facts["deployment"]["app_url"]
        enabled = [k for k, v in baseline.items() if v]
        _check(checks, "CD-2", "AI-Mode, MCP, RAG and Multi-Agent are disabled in the cloud baseline",
               bool(baseline) and not enabled, f"switches: {baseline}" if baseline else "No cloud_baseline recorded.",
               missing=not baseline)
        smoke = facts["deployment"]["smoke_test"]
        _check(checks, "CD-3", "The deploy's own smoke test passed", smoke == "pass", f"smoke_test.result={smoke}")
        crud = report.get("crud_test") or {}
        facts["deployment"]["crud_test"] = crud
        crud_matches = (
            bool(deployment.get("commit"))
            and crud.get("commit") == deployment.get("commit")
            and crud.get("workflow_run_url") == (deployment.get("workflow_run_url") or "")
            and crud.get("target") == facts["deployment"]["app_url"]
        )
        _check(checks, "CD-CRUD", "CRUD and persistence passed for this deployment",
               crud.get("result") == "pass" and crud_matches,
               f"CRUD result={crud.get('result', 'unverified')}; matching source/run/target={crud_matches}",
               missing=not crud or crud.get("result") == "unverified")
        public = [a.get("name") for a in apps if a.get("external")]
        stopped = [a.get("name") for a in apps if str(a.get("status", "")).lower() not in ("running", "succeeded")]
        _check(checks, "CD-4", "All container apps run and only one has public ingress",
               bool(apps) and not stopped and len(public) == 1,
               f"{len(apps)} apps; public: {public}; not running: {stopped or 'none'}", missing=not apps)
        exposed = [d.get("name") for d in postgres if str(d.get("publicNetworkAccess")).lower() != "disabled"]
        _check(checks, "CD-5", "The managed PostgreSQL database has no public network access",
               bool(postgres) and not exposed, f"{len(postgres)} servers; public: {exposed or 'none'}",
               missing=not postgres)
        # The deployed commit must be one that CI passed on.
        commit = deployment.get("commit")
        api = f"https://api.github.com/repos/{args.repo}"
        try:
            runs = _get_json(f"{api}/actions/runs?head_sha={commit}&per_page=30").get("workflow_runs", [])
            ci = [r for r in runs if r.get("path", "").endswith(tuple(args.workflows))]
            _check(checks, "CD-6", "The deployed commit passed CI first",
                   bool(ci) and all(r["conclusion"] == "success" for r in ci),
                   ", ".join(f"{r['name']}={r['conclusion']}" for r in ci) or f"No CI run found for {str(commit)[:7]}.")
        except (error.URLError, TimeoutError, ValueError) as exc:
            _check(checks, "CD-6", "The deployed commit passed CI first", False, f"GitHub API unavailable: {exc}",
                   missing=True)

    if not args.url:
        _check(checks, "CD-7", "The deployed frontend answers over HTTPS", False,
               "No deployment URL (no --url and none in the report).", missing=True)
    else:
        base = args.url.rstrip("/")
        sources.append(base)
        _check(checks, "CD-7", "The deployed frontend answers over HTTPS", base.startswith("https://"), base)
        for number, path in enumerate(args.paths, start=8):
            status, seconds, body = _probe(base + path)
            facts["probes"].append({"path": path, "status": status, "seconds": round(seconds, 2)})
            _check(checks, f"CD-{number}", f"{path} responds on the live deployment",
                   status is not None and status < 400,
                   f"HTTP {status} in {seconds:.1f}s" if status else f"unreachable: {body}")

    api = f"https://api.github.com/repos/{args.repo}"
    try:
        runs = _get_json(f"{api}/actions/workflows/{args.deploy_workflow}/runs?branch={args.branch}&per_page=5")
        runs = [r for r in runs.get("workflow_runs", []) if r["status"] == "completed"]
    except error.HTTPError as exc:
        runs = [] if exc.code == 404 else None
    except (error.URLError, TimeoutError, ValueError):
        runs = None
    title = f"The latest {args.deploy_workflow} run on {args.branch} succeeded"
    if runs:
        run = runs[0]
        facts["deploy_run"] = {"run_id": run["id"], "commit": run["head_sha"][:7],
                               "conclusion": run["conclusion"], "url": run["html_url"]}
        sources.append(run["html_url"])
        _check(checks, "CD-W", title, run["conclusion"] == "success",
               f"run {run['id']} on {run['head_sha'][:7]}: {run['conclusion']}")
    else:
        _check(checks, "CD-W", title, False, "GitHub API unavailable." if runs is None
               else f"No finished {args.deploy_workflow} run on {args.branch}.", missing=True)
    return facts, checks, sources


GATHER = {"multi-agent": gather_multi_agent, "testing": gather_testing, "cloud-deployment": gather_cloud}


# --------------------------------------------------------------------------- #
# ACT and OBSERVE                                                             #
# --------------------------------------------------------------------------- #


def draft_review(args, grounding: dict, feedback: str | None) -> dict:
    payload = {
        "model": args.model,
        "stream": False,
        "format": REVIEW_SCHEMA,
        "messages": [
            {"role": "system", "content": DRAFT_PROMPT.format(subject=SUBJECTS[args.mode])},
            {"role": "user", "content": json.dumps(
                {"EVIDENCE": grounding, **({"REVIEWER_FEEDBACK": feedback} if feedback else {})},
                ensure_ascii=False)},
        ],
        "options": {"temperature": 0, "num_predict": 1600, "num_ctx": args.num_ctx},
    }
    req = request.Request(  # noqa: S310 -- --ollama-url scheme checked in main()
        f"{args.ollama_url.rstrip('/')}/api/chat", data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with request.urlopen(req, timeout=args.timeout) as response:  # noqa: S310 -- checked in main()
            body = json.loads(response.read().decode("utf-8"))
        return json.loads(body["message"]["content"])
    except (error.URLError, TimeoutError, ValueError, KeyError, TypeError) as exc:
        raise LoopError(f"Draft call failed: {exc}") from exc


def rule_issues(draft: dict, checks: list[Check]) -> list[str]:
    """Rules a draft must meet regardless of what the second model thinks."""
    issues = []
    if not isinstance(draft, dict) or not all(k in draft for k in ("summary", "findings", "recommendations", "verdict")):
        return ["The draft must have summary, findings, recommendations and verdict."]
    ids = {c.id for c in checks}
    findings = [f for f in draft.get("findings") or [] if isinstance(f, dict)]
    unknown = sorted({str(f.get("check_id")) for f in findings} - ids)
    if unknown:
        issues.append(f"Findings cite check ids that do not exist: {', '.join(unknown)}.")
    raised = {f.get("check_id") for f in findings if f.get("severity") in ("major", "blocker")}
    noted = {f.get("check_id") for f in findings if f.get("severity") in ("minor", "major", "blocker")}
    for check in checks:
        if check.status in BLOCKING and check.id not in raised:
            issues.append(f"Check {check.id} is {check.status} but has no major or blocker finding.")
        elif check.status == "warn" and check.id not in noted:
            issues.append(f"Check {check.id} warns but has no minor (or higher) finding.")
    if draft.get("verdict") not in VERDICTS:
        issues.append(f"The verdict must be one of {', '.join(VERDICTS)}.")
    elif draft["verdict"] != "not_ready" and any(c.status in BLOCKING for c in checks):
        issues.append("The verdict must be not_ready while any check fails or is missing.")
    elif draft["verdict"] == "ready" and any(c.status == "warn" for c in checks):
        issues.append("The verdict cannot be ready while a check warns; use ready_with_fixes.")
    if not str(draft.get("summary") or "").strip():
        issues.append("The summary is empty.")
    return issues


def deterministic_review(checks: list[Check]) -> dict:
    """The review written from the checks alone, used with --no-model."""
    bad = [c for c in checks if c.status != "pass"]
    severity = {"missing": "blocker", "fail": "major", "warn": "minor"}
    blocking = any(c.status in BLOCKING for c in bad)
    return {
        "summary": f"{len(checks) - len(bad)} of {len(checks)} checks passed."
        + (f" Not passing: {', '.join(f'{c.id} ({c.status})' for c in bad)}." if bad else ""),
        "findings": [{"check_id": c.id, "severity": severity[c.status],
                      "finding": f"{c.title}: {c.detail}"} for c in bad],
        "recommendations": [f"Resolve {c.id}: {c.title.lower()}." for c in bad],
        "verdict": "not_ready" if blocking else "ready_with_fixes" if bad else "ready",
    }


def render(mode: str, review: dict, checks: list[Check], decision: dict) -> str:
    lines = [f"Verdict: {review['verdict']}", "", review["summary"], "", "Checks:"]
    lines += [f"  [{c.status:7}] {c.id} {c.title} - {c.detail}" for c in checks]
    lines += ["", "Findings:"] + [f"  {f['check_id']} ({f['severity']}): {f['finding']}" for f in review["findings"]]
    lines += ["", "Recommendations:"] + [f"  - {r}" for r in review["recommendations"]]
    lines += ["", f"Human decision ({'/'.join(DECISIONS[mode])}): {decision['decision']}"
              + (f" - {decision['reason']}" if decision.get("reason") else "")]
    return "\n".join(lines)


def render_markdown(result: dict) -> str:
    """The review report for the technical report: checks, findings, decision."""
    mode, review, decision = result["mode"], result["review"], result["human_review"]
    icon = {"pass": "✅ pass", "warn": "⚠️ warn", "fail": "❌ fail", "missing": "❔ missing"}
    lines = [
        f"# {mode.replace('-', ' ').title()} review",
        "",
        f"Run `{result['run_id']}` · verdict **{review['verdict']}** (from {result['verdict_source'].replace('_', ' ')})"
        f" · human decision **{decision['decision']}**"
        + (f" by `{decision.get('reviewer_id')}`" if decision.get("reviewer_id") else ""),
        "",
        review["summary"],
        "",
        "## Checks",
        "",
        "| ID | Check | Result | Detail |",
        "| --- | --- | --- | --- |",
    ]
    for check in result["checks"]:
        detail = check["detail"].replace("|", "\\|")
        lines.append(f"| {check['id']} | {check['title']} | {icon.get(check['status'], check['status'])} | {detail} |")
    coverage = result["facts"].get("test_evidence") if isinstance(result["facts"], dict) else None
    if coverage:
        lines += ["", "## Tests and endpoint coverage per service", "",
                  "| Service | Tests | Failures + errors | Skipped | Warnings | Line coverage | Endpoints exercised |",
                  "| --- | --- | --- | --- | --- | --- | --- |"]
        for row in coverage:
            lines.append(f"| `{row['service']}` | {row['tests']} | {row['failures'] + row['errors']} | {row['skipped']} | "
                         f"{row['warnings']} | {row['line_coverage_percent']}% | {row['endpoints_tested']}/{row['endpoints']} |")
        gaps = [row for row in coverage if row["untested_endpoints"]]
        if gaps:
            lines += ["", "### Endpoints no test exercises", ""]
            for row in gaps:
                lines.append(f"- **`{row['service']}`**: " + ", ".join(f"`{e}`" for e in row["untested_endpoints"]))
    lines += ["", "## Findings", ""]
    lines += [f"- **{f['check_id']}** ({f['severity']}): {f['finding']}" for f in review["findings"]] or ["- None."]
    lines += ["", "## Recommendations", ""]
    lines += [f"- {r}" for r in review["recommendations"]] or ["- None."]
    lines += ["", "## Human decision", "",
              f"- Decision: **{decision['decision']}** (choices: {', '.join(DECISIONS[mode])})",
              f"- Reason: {decision.get('reason') or '(none given)'}",
              "", "## Evidence and log", ""]
    lines += [f"- {source}" for source in result["evidence_sources"]]
    lines += [f"- Review/validation log: `{_rel(Path(result['transcript']))}`", "",
              f"_{result['scope']}_", ""]
    return "\n".join(lines)


def ask_human(args, review: dict) -> dict:
    choices = DECISIONS[args.mode]
    if args.decision:
        return {"decision": args.decision, "reason": args.reason or "", "reviewer_id": args.reviewer_id}
    if not sys.stdin.isatty():
        return {"decision": "pending", "reason": "No --decision given and no terminal to ask.",
                "reviewer_id": args.reviewer_id}
    print(f"\nReview verdict: {review['verdict']}. {review['summary']}", file=sys.stderr)
    choice = ""
    while choice not in choices:
        choice = input(f"Your decision ({'/'.join(choices)}): ").strip()
    reason = input("Reason (optional): ").strip()
    return {"decision": choice, "reason": reason, "reviewer_id": args.reviewer_id}


# --------------------------------------------------------------------------- #
# The loop                                                                    #
# --------------------------------------------------------------------------- #


def run_review(args) -> dict:
    service = f"review-{args.mode}"
    log_dir = str(args.log_dir or ROOT / "tools" / "ai-loop" / "logs")
    os.makedirs(log_dir, exist_ok=True)
    run_id = f"{service}-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}"
    logger = LoopLogger(service, log_dir, run_id, f"Review {SUBJECTS[args.mode]}",
                        workflow="Plan → Act → Observe → Adapt → Human review")

    # -- PLAN --
    facts, checks, sources = GATHER[args.mode](args)
    grounding = {"mode": args.mode, "checks": [asdict(c) for c in checks], "facts": facts}
    logger.phase("plan", {
        "mode": args.mode, "evidence_sources": sources,
        "checks": "; ".join(f"{c.id}={c.status}" for c in checks),
        "failing_checks": [c.id for c in checks if c.status != "pass"],
        "model": None if args.no_model else args.model,
        "review_model": None if args.no_model or args.no_review_model else args.review_model,
        "max_iterations": args.max_iterations,
    })

    review, verdict_source, iterations = None, "model", 0
    if args.no_model:
        review, verdict_source = deterministic_review(checks), "checks_only"
        logger.phase("fallback", {"reason": "--no-model: review written from the checks only"},
                     body=json.dumps(review, ensure_ascii=False, indent=2))
    else:
        reviewer = None if args.no_review_model else Reviewer(
            args.ollama_url, args.review_model, timeout=args.timeout, num_predict=800, prompt=OBSERVE_PROMPT,
            num_ctx=args.num_ctx)
        feedback = None
        try:
            ensure_model(args.ollama_url, args.model, auto_pull=False)
            for iterations in range(1, args.max_iterations + 1):
                # -- ACT --
                started = time.monotonic()
                draft = draft_review(args, grounding, feedback)
                logger.phase("act", {"iteration": iterations, "carried_feedback": feedback or "(none)",
                                     "ms": int((time.monotonic() - started) * 1000)},
                             body=json.dumps(draft, ensure_ascii=False, indent=2))
                # -- OBSERVE: rules first, then the independent model --
                issues = rule_issues(draft, checks)
                model_review = {"verdict": "skipped", "issues": [], "guidance": ""}
                if not issues and reviewer is not None:
                    started = time.monotonic()
                    try:
                        model_review = reviewer.review(f"Review {SUBJECTS[args.mode]}", grounding,
                                                       json.dumps(draft, ensure_ascii=False))
                    except LoopError as exc:
                        # The draft already met every rule; keep it rather than discard it, and
                        # say plainly that the second-model check did not happen.
                        model_review = {"verdict": "unavailable", "issues": [f"second review failed: {exc}"],
                                        "guidance": ""}
                        verdict_source = "model_rules_only"
                    if model_review["verdict"] == "revise":
                        issues = model_review["issues"] or ["The reviewer asked for a revision."]
                logger.phase("observe", {"iteration": iterations, "rule_issues": rule_issues(draft, checks) or "(none)",
                                         "reviewer_verdict": model_review["verdict"],
                                         "reviewer_issues": "; ".join(model_review["issues"]) or "(none)"})
                review = draft
                # -- ADAPT --
                if not issues:
                    logger.phase("adapt", {"iteration": iterations, "decision": "accept"})
                    break
                feedback = "; ".join(issues) + (f" Guidance: {model_review['guidance']}" if model_review.get("guidance") else "")
                last = iterations == args.max_iterations
                logger.phase("adapt", {"iteration": iterations,
                                       "decision": "stop_capped" if last else "revise", "guidance": feedback})
            if review is not None and rule_issues(review, checks):
                # The model never met the rules: fall back to the checks rather than
                # report a verdict the evidence does not support.
                review, verdict_source = deterministic_review(checks), "checks_after_capped_model"
                logger.phase("fallback", {"reason": "draft still broke the rules after the last iteration"},
                             body=json.dumps(review, ensure_ascii=False, indent=2))
        except LoopError as exc:
            review, verdict_source = deterministic_review(checks), "checks_only"
            logger.phase("fallback", {"reason": str(exc)}, body=json.dumps(review, ensure_ascii=False, indent=2))

    # -- HUMAN --
    decision = ask_human(args, review)
    logger.phase("human_review", decision)
    rendered = render(args.mode, review, checks, decision)
    logger.phase("result", {"verdict": review["verdict"], "verdict_source": verdict_source,
                            "decision": decision["decision"]}, body=rendered)
    print(rendered, file=sys.stderr)
    result = {
        "run_id": run_id,
        "mode": args.mode,
        "passed": not any(c.status in BLOCKING for c in checks),
        "checks": [asdict(c) for c in checks],
        "facts": facts,
        "review": review,
        "verdict_source": verdict_source,
        "iterations": iterations,
        "human_review": decision,
        "evidence_sources": sources,
        "transcript": logger.transcript_path,
        "scope": "Reviews saved evidence; a passing review is not proof that every feature works.",
    }
    if getattr(args, "report", None):
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(render_markdown(result), encoding="utf-8")
        result["report"] = _rel(Path(args.report))
    return result

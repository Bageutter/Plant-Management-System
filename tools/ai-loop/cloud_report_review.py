#!/usr/bin/env python3
"""Cloud Deployment Report Review: the shared agentic loop reviews one deployment report.

    python tools/ai-loop/cloud_report_review.py
    python tools/ai-loop/cloud_report_review.py --report docs/evidence/release2/cloud-deployment/cloud-deployment-<stamp>.json

Reads the JSON report `scripts/deploy/azure-report.sh` wrote (default
`docs/evidence/release2/cloud-deployment/latest.json`) and recommends
approve / approve_with_corrections / reject to the human release manager, or
refuses with insufficient_evidence when the report lacks a smoke result or the
four cloud baseline flags. Any enabled AI service is flagged as a baseline breach.

The mode itself lives in `shared/ai_loop.py` (grounding builder, pinned decision
schema, drafter, reviewer and the release rules enforced in code) and runs through
the same Plan -> Act -> Observe -> Adapt loop as the chat features: a proposer
model drafts the structured decision from a JSON grounding built in code, an
independent reviewer model checks it against the same grounding, and the loop
revises until approved or capped. Both models run on local Ollama only.

This is the report-level review. `validate.py --mode cloud-deployment` (in
`review.py`) is the checks-based release review of the same deployment: it also
probes the live site and the GitHub workflow runs and records the human decision.
Use both for the technical report; they write to different log services.

Evidence: the three sinks every loop run writes (stdout, `logs/cloud-deployment.jsonl`,
`logs/reports/cloud-deployment/<run_id>.md`), the JSON result on stdout, and a
review/validation log (`.md` + `.json`) copied next to the report, ending with the
final human release decision checklist. See README.md.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
LOG_DIR = Path(__file__).resolve().parent / "logs"
sys.path.insert(0, str(ROOT / "shared"))
import ai_loop  # noqa: E402 -- the shared loop; sys.path entry above

DEFAULT_CLOUD_REPORT = ROOT / "docs" / "evidence" / "release2" / "cloud-deployment" / "latest.json"
MODEL_TIMEOUT = 180  # one local model call; the same bound the health service uses

# exit codes: the decision, so a shell step can gate on it
EXIT_CODES = {"approve": 0, "approve_with_corrections": 0, "reject": 1, "insufficient_evidence": 2}
EXIT_LOOP_ERROR = 3


def load_report(path: Path) -> dict:
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(
            f"No report at {path}. Run scripts/deploy/azure-report.sh (or the cloud deployment "
            "workflow) first, or pass --report <path to cloud-deployment-<stamp>.json>."
        ) from None
    except (OSError, ValueError) as exc:
        raise SystemExit(f"Could not read the report at {path}: {exc}") from exc
    if not isinstance(report, dict):
        raise SystemExit(f"The report at {path} is not a JSON object.")
    return report


def _md_cell(value) -> str:
    return " ".join(str(value if value is not None else "").split()).replace("|", "\\|")


def _table(headers: list[str], rows: list[list]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    for row in rows:
        lines.append("| " + " | ".join(_md_cell(cell) for cell in row) + " |")
    return "\n".join(lines)


def render_cloud_validation_log(
    decision: dict,
    result: ai_loop.LoopResult,
    report_path: Path,
    report: dict,
    models: dict,
    corrections: list[str] | None = None,
) -> str:
    """The review/validation log for the technical report (criterion 8)."""
    grounding, plan = ai_loop.build_cloud_deployment_grounding(report)
    deployment = grounding["deployment"]
    trace_rows = []
    for event in result.trace:
        phase = event["phase"]
        if phase == "plan":
            outcome = " ".join(f"{k}={v}" for k, v in plan.items())
        elif phase == "act":
            outcome = f"draft of {event.get('draft_chars')} chars; feedback: {event.get('carried_feedback')}"
        elif phase == "observe":
            outcome = f"{event.get('verdict')}; issues: {event.get('issues')}"
        elif phase == "fallback":
            outcome = f"fallback: {event.get('reason')}"
        else:
            outcome = str(event.get("decision", ""))
            if event.get("guidance"):
                outcome += f"; guidance: {event['guidance']}"
        trace_rows.append([phase.upper(), event.get("iteration", ""), outcome, event.get("elapsed_ms", "")])

    findings = decision.get("findings") or []
    findings_md = (
        _table(
            ["#", "Severity", "Area", "Evidence", "Recommendation"],
            [
                [i, f["severity"], f["area"], f["evidence"], f["recommendation"]]
                for i, f in enumerate(findings, start=1)
            ],
        )
        if findings
        else "_No findings._"
    )
    loop_verdict = {
        "approved": "approved by the independent reviewer",
        "revised_capped": "iteration cap reached without reviewer approval; read the OBSERVE issues below",
        "fallback": "single-shot, no reviewer (see the FALLBACK row)",
    }.get(result.verdict, result.verdict)
    try:
        shown_path = report_path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        shown_path = str(report_path)
    corrections_md = (
        "\n".join(f"- {note}" for note in corrections)
        if corrections
        else "_None: the final draft already satisfied every release rule._"
    )

    return f"""# Cloud Deployment Report Review — validation log

Produced by `python tools/ai-loop/cloud_report_review.py` (shared agentic loop,
Plan → Act → Observe → Adapt, local Ollama only). This log is advisory: it
supports the final human release decision and does not replace it.

| | |
|---|---|
| Report reviewed | `{shown_path}` (generated {grounding["report"].get("generated_at")}) |
| Commit | `{deployment.get("commit")}` on `{deployment.get("branch")}` |
| Workflow run | {deployment.get("workflow_run_url") or "(run locally)"} |
| Loop run | `{result.run_id}` — {result.iterations} iteration(s), {loop_verdict} |
| Proposer / reviewer | `{models.get("proposer")}` / `{models.get("reviewer") or "(none)"}` at `{models.get("ollama_url")}` |
| Transcript | `{Path(result.transcript_path).as_posix()}` |
| Reviewed at | {datetime.now(timezone.utc).isoformat(timespec="seconds")} |

## Decision

| Decision | Cloud baseline compliant | Smoke test | Evidence gaps |
|---|---|---|---|
| **{decision["decision"]}** | {"yes" if decision["baseline_compliant"] else "NO"} | {grounding["smoke_test"]["result"] or "missing"} | {len(grounding["evidence_gaps"])} |

**Release recommendation:** {decision["release_recommendation"]}

Decision meanings: `approve` = release stands; `approve_with_corrections` = release
stands, fix the findings in a follow-up; `reject` = roll back or redeploy;
`insufficient_evidence` = the report cannot be reviewed (no smoke result, or a
cloud baseline flag missing) — regenerate it.

## Findings

{findings_md}

## Code corrections applied to the final draft

The model's output is untrusted: `normalise_cloud_decision()` in `shared/ai_loop.py`
re-validates it against the grounding and the release rules. Changes it made:

{corrections_md}

## Grounding the reviewer used

Cloud baseline switches: {", ".join(f"{k}={v}" for k, v in grounding["cloud_baseline"].items())}.
Container apps: {len(grounding["container_apps"])}; PostgreSQL servers: {len(grounding["postgres"])};
key vaults: {len(grounding["key_vaults"])}; storage accounts: {len(grounding["storage_accounts"])};
security controls claimed: {len(grounding["security_controls"])}. The full grounding is in the
PLAN phase of the JSONL log (`tools/ai-loop/logs/cloud-deployment.jsonl`).

## Loop trace

{_table(["Phase", "Iteration", "Outcome", "+ms"], trace_rows)}

## Final human release decision

To be completed by the release manager after reading this log and the report:

- [ ] **Approved** — release stands
- [ ] **Approved with corrections** (list):
- [ ] **Rejected** — roll back / redeploy (reason):

Reviewer: ______________________  Date: ____________
"""


def _report_stamp(report: dict, run_id: str) -> str:
    generated = report.get("generated_at")
    if isinstance(generated, str) and generated.strip():
        return generated.strip().replace("-", "").replace(":", "")
    return run_id


def run_cloud_deployment(args: argparse.Namespace, drafter=None, reviewer=None) -> dict:
    report_path = Path(args.report)
    report = load_report(report_path)
    models = {"proposer": args.model, "reviewer": args.review_model or None, "ollama_url": args.ollama_url}
    if drafter is None:
        drafter = ai_loop.CloudDeploymentDrafter(
            base_url=args.ollama_url, model=args.model, timeout=MODEL_TIMEOUT, auto_pull=args.auto_pull
        )
    if reviewer is None and args.review_model:
        reviewer = ai_loop.Reviewer(
            base_url=args.ollama_url,
            model=args.review_model,
            timeout=MODEL_TIMEOUT,
            auto_pull=args.auto_pull,
            num_predict=400,
            prompt=ai_loop.PROMPT_CLOUD_DEPLOYMENT_OBSERVE,
        )

    decision, result = ai_loop.review_cloud_deployment(
        report, drafter, reviewer, str(args.log_dir), max_iterations=args.max_iterations
    )

    corrections = list(getattr(drafter, "last_corrections", []))
    log_md = render_cloud_validation_log(decision, result, report_path, report, models, corrections)
    summary = {
        "mode": "cloud-deployment",
        "report": str(report_path),
        "run_id": result.run_id,
        "models": models,
        "loop": {
            "workflow": "Plan -> Act -> Observe -> Adapt",
            "verdict": result.verdict,
            "iterations": result.iterations,
            "transcript": result.transcript_path,
        },
        "decision": decision,
        "code_corrections": corrections,
        "validation_log": None,
        "scope": (
            "Advisory review of the deployment report's recorded facts; the final release "
            "decision is the release manager's."
        ),
    }
    copy_dir = None if args.no_copy else Path(args.copy_dir or report_path.parent)
    if copy_dir is not None:
        copy_dir.mkdir(parents=True, exist_ok=True)
        stamp = _report_stamp(report, result.run_id)
        md_path = copy_dir / f"cloud-deployment-{stamp}-review.md"
        json_path = copy_dir / f"cloud-deployment-{stamp}-review.json"
        summary["validation_log"] = {"markdown": str(md_path), "json": str(json_path)}
        md_path.write_text(log_md, encoding="utf-8")
        json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        for latest, source in (("latest-review.md", md_path), ("latest-review.json", json_path)):
            (copy_dir / latest).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--report", default=str(DEFAULT_CLOUD_REPORT),
        help="the JSON report to review (default: docs/evidence/release2/cloud-deployment/latest.json)",
    )
    parser.add_argument(
        "--ollama-url", default=os.environ.get("OLLAMA_URL", "http://localhost:11434"),
        help="local Ollama base URL (env OLLAMA_URL)",
    )
    parser.add_argument(
        "--model", default=os.environ.get("OLLAMA_MODEL", "qwen3:4b-instruct"),
        help="proposer model for ACT (env OLLAMA_MODEL)",
    )
    parser.add_argument(
        "--review-model", default=os.environ.get("OLLAMA_REVIEW_MODEL", "llama3.1:8b"),
        help="independent reviewer model for OBSERVE (env OLLAMA_REVIEW_MODEL); '' for single-shot",
    )
    parser.add_argument(
        "--max-iterations", type=int, default=int(os.environ.get("AI_LOOP_MAX_ITERATIONS", "2")),
        help="ACT/OBSERVE rounds before the loop stops (env AI_LOOP_MAX_ITERATIONS)",
    )
    parser.add_argument(
        "--auto-pull", action="store_true",
        default=os.environ.get("OLLAMA_AUTO_PULL", "").lower() in ("1", "true", "yes"),
        help="pull a missing model once instead of failing (env OLLAMA_AUTO_PULL)",
    )
    parser.add_argument("--log-dir", type=Path, default=LOG_DIR, help="JSONL + transcript directory")
    parser.add_argument(
        "--copy-dir", type=Path, default=None,
        help="where to write the validation log copies (default: next to the report)",
    )
    parser.add_argument("--no-copy", action="store_true", help="do not copy the validation log next to the report")
    parser.add_argument("--output", type=Path, help="also save the JSON result to this file")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if urlparse(args.ollama_url).scheme not in ("http", "https"):
        parser.error("--ollama-url must be an http or https URL")
    if args.max_iterations < 1:
        parser.error("--max-iterations must be at least 1")
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        summary = run_cloud_deployment(args)
    except ai_loop.LoopError as exc:
        print(json.dumps({"mode": "cloud-deployment", "error": str(exc)}, indent=2))
        return EXIT_LOOP_ERROR
    output = json.dumps(summary, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output + "\n", encoding="utf-8")
    print(output)
    return EXIT_CODES.get(summary["decision"]["decision"], EXIT_LOOP_ERROR)


if __name__ == "__main__":
    raise SystemExit(main())

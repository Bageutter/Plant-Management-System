#!/usr/bin/env python3
"""Evidence-report reviews of the shared agentic loop (Release 2), run from the terminal.

    python tools/ai-loop/evidence_review.py --mode multi-agent [--evidence-dir <folder> | --server http://127.0.0.1:8003]
    python tools/ai-loop/evidence_review.py --mode testing [--pre-commit-dir <folder> --post-commit-dir <folder>]

Each mode has the loop *read the committed evidence itself* through the same
Plan -> Act -> Observe -> Adapt loop the chat features use (`shared/ai_loop.py`):
the code computes the facts and the violations, a proposer model drafts a
structured review pinned to a schema, the code re-validates it and enforces the
rules, and an independent reviewer model observes it. Both models run on local
Ollama only. These complement `validate.py --mode multi-agent|testing` (in
`review.py`), the checks-based reviews that also read the committer-local
`.security-reports/` and the GitHub Actions API and record the human decision;
the cloud report has the same pair in `cloud_report_review.py`. They log to
different services so `view.py` keeps them apart.

Modes:

- ``multi-agent`` — Multi-Agent Workflow Review (`multi_agent_review.py`). Reads
  the Multi-Agent Server's exports (`workflow_history.jsonl`,
  `coordination_audit.jsonl`, `multi-agent-metrics.json`; default folder
  `docs/evidence/release2`, or live from `--server`) and checks every run went
  Planner -> Worker -> Reviewer -> human decision, that Worker citations are in the
  evidence, that a `revise` was closed with a reason, and that audit and metrics
  agree; then recommends implementation and review improvements.
- ``testing`` — Testing Report Review (`testing_review.py`). Reads the committed
  pre-commit security report pages (`docs/evidence/release2/pre-commit/*.md`) and
  the post-commit CI/CD artifact folders (`docs/evidence/release2/post-commit/*/`)
  and checks the four required scans ran and passed, and that each student's two
  endpoint functions were tested on a successful push run with the regressions
  green.

Evidence: the three sinks every loop run writes (stdout, `logs/<mode>.jsonl`,
`logs/reports/<mode>/<run_id>.md`), the JSON result on stdout, and a
review/validation log (`.md` + `.json`) copied to
`docs/evidence/release2/agentic-review/` for the technical report's human
confirmation. See README.md.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
LOG_DIR = Path(__file__).resolve().parent / "logs"
sys.path.insert(0, str(ROOT / "shared"))
sys.path.insert(0, str(Path(__file__).resolve().parent))  # the sibling mode modules (hyphenated folder)
import ai_loop  # noqa: E402 -- the shared loop; sys.path entry above
import multi_agent_review  # noqa: E402 -- Multi-Agent Workflow Review mode
import testing_review  # noqa: E402 -- Testing Report Review mode

# exit codes: the verdict, so a shell step can gate on it
EXIT_CODES = {"pass": 0, "pass_with_findings": 0, "fail": 1, "insufficient_evidence": 2}
EXIT_LOOP_ERROR = 3

MODES = {
    "multi-agent": multi_agent_review.run,
    "testing": testing_review.run,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--mode", choices=sorted(MODES), required=True)
    parser.add_argument(
        "--evidence-dir", default=str(multi_agent_review.DEFAULT_EVIDENCE_DIR),
        help="multi-agent: folder holding workflow_history.jsonl, coordination_audit.jsonl and "
        "multi-agent-metrics.json (default: docs/evidence/release2; the Plant Health export is "
        "docs/evidence/release2/local-deployment)",
    )
    parser.add_argument(
        "--server", default=None,
        help="multi-agent: review the live Multi-Agent Server instead of files, e.g. http://127.0.0.1:8003",
    )
    parser.add_argument("--workflow-id", default=None, help="multi-agent: review this one workflow only")
    parser.add_argument(
        "--pre-commit-dir", default=str(testing_review.DEFAULT_PRE_COMMIT_DIR),
        help="testing: folder of scripts/security/report.py pages (default: docs/evidence/release2/pre-commit)",
    )
    parser.add_argument(
        "--post-commit-dir", default=str(testing_review.DEFAULT_POST_COMMIT_DIR),
        help="testing: folder of CI artifact folders with run.json + JUnit files "
        "(default: docs/evidence/release2/post-commit)",
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
        help="where to write the validation log copies (default: docs/evidence/release2/agentic-review)",
    )
    parser.add_argument("--no-copy", action="store_true", help="do not copy the validation log next to the evidence")
    parser.add_argument("--output", type=Path, help="also save the JSON result to this file")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if urlparse(args.ollama_url).scheme not in ("http", "https"):
        parser.error("--ollama-url must be an http or https URL")
    if args.server and urlparse(args.server).scheme not in ("http", "https"):
        parser.error("--server must be an http or https URL")
    if args.max_iterations < 1:
        parser.error("--max-iterations must be at least 1")
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        summary = MODES[args.mode](args)
    except ai_loop.LoopError as exc:
        print(json.dumps({"mode": args.mode, "error": str(exc)}, indent=2))
        return EXIT_LOOP_ERROR
    output = json.dumps(summary, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output + "\n", encoding="utf-8")
    print(output)
    return EXIT_CODES.get(summary["decision"]["decision"], EXIT_LOOP_ERROR)


if __name__ == "__main__":
    raise SystemExit(main())

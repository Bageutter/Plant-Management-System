#!/usr/bin/env python3
"""Validate shared MCP or RAG through a running feature backend, without writes."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib import error, request
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
MAX_ATTEMPTS = 2
HTTP_TIMEOUT = 190  # Allow the backend's 180-second local model request to finish.
sys.path.insert(0, str(ROOT / "shared"))
from ai_loop import LoopLogger  # noqa: E402 -- reuse the project's native logger


def post_json(url: str, payload: dict, timeout: int) -> dict:
    req = request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=timeout) as response:
        body = json.load(response)
    if not isinstance(body, dict):
        raise ValueError("The backend response must be a JSON object.")
    return body


def check_mcp(body: dict, payload: dict) -> list[str]:
    issues = []
    if body.get("tool") != payload["tool"] or body.get("is_error") is not False:
        issues.append("The requested MCP tool did not return a successful result.")
    page = body.get("structured_content")
    if not isinstance(page, dict) or not isinstance(page.get("items"), list):
        return issues + ["MCP must return structured_content with an items list."]
    items = page["items"]
    if not items or len(items) > payload["limit"]:
        issues.append("The seeded search must return between 1 and the requested limit of records.")
    for item in items:
        if not isinstance(item, dict):
            issues.append("Every search result must be a structured record.")
            continue
        for key in ("key", "name", "uri", "path"):
            if not isinstance(item.get(key), str) or not item[key].strip():
                issues.append(f"A search result is missing its {key} reference.")
        if type(item.get("id")) is not int or item["id"] < 1:
            issues.append("A search result must have a positive integer id.")
        if payload["query"].lower() not in str(item.get("name", "")).lower():
            issues.append("A returned record does not match the requested catalogue name.")
        if item.get("kind") not in ("plant", "pest", "disease"):
            issues.append("A search result has an unknown record kind.")
        elif payload["kind"] != "all" and item["kind"] != payload["kind"]:
            issues.append("The search did not respect the requested record kind.")
    return list(dict.fromkeys(issues))


def check_rag(body: dict, *, refuse: bool) -> list[str]:
    issues = []
    if refuse:
        if body.get("insufficient_context") is not True:
            issues.append("The unrelated question must report insufficient context.")
        if body.get("confidence") != "insufficient":
            issues.append("A refusal must have insufficient confidence.")
        if body.get("answer") not in (None, "") or body.get("citations") != []:
            issues.append("A refusal must not invent an answer or cite unrelated records.")
        return issues
    if body.get("insufficient_context") is not False:
        issues.append("The seeded disease question did not produce a grounded answer.")
    if not isinstance(body.get("answer"), str) or not body["answer"].strip():
        issues.append("The grounded answer must contain text.")
    if body.get("confidence") not in ("low", "medium", "high"):
        issues.append("The answer must report a valid confidence category.")
    citations = body.get("citations")
    if not isinstance(citations, list) or not citations:
        return issues + ["The answer must cite at least one Almanac passage."]
    for citation in citations:
        if not isinstance(citation, dict):
            issues.append("Each citation must be a structured record.")
            continue
        if citation.get("source") != "almanac":
            issues.append("The answer cited a source outside the Almanac.")
        for key in ("chunk_id", "source_id", "title", "url", "excerpt"):
            if not str(citation.get(key) or "").strip():
                issues.append(f"A citation is missing its {key}.")
    return list(dict.fromkeys(issues))


def cases_for(mode: str) -> list[dict]:
    if mode == "mcp":
        return [
            {
                "name": name,
                "path": "/integrations/mcp",
                "payload": {
                    "tool": "search_almanac_catalogue",
                    "query": query,
                    "kind": kind,
                    "limit": 5,
                },
            }
            for name, query, kind in (
                ("plant_search", "tomato", "all"),
                ("disease_search", "powdery mildew", "disease"),
            )
        ]
    return [
        {
            "name": "grounded_answer",
            "path": "/integrations/rag",
            "payload": {"question": "What helps prevent powdery mildew?"},
        },
        {
            "name": "unrelated_refusal",
            "path": "/integrations/rag",
            "payload": {"question": "Who won the 1986 FIFA World Cup?"},
        },
    ]


def run(args: argparse.Namespace) -> dict:
    run_id = f"validate-{args.mode}-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}"
    logger = LoopLogger(
        "almanac", str(getattr(args, "log_dir", None) or ROOT / "tools" / "ai-loop" / "logs"), run_id,
        f"Validate {args.mode} integration",
    )
    pending = cases_for(args.mode)
    results = {}
    logger.phase("plan", {
        "mode": args.mode,
        "base_url": args.base_url,
        "checks": [case["name"] for case in pending],
        "max_attempts": MAX_ATTEMPTS,
        "read_only": True,
    })
    for iteration in range(1, MAX_ATTEMPTS + 1):
        retry = []
        for case in pending:
            name, payload = case["name"], case["payload"]
            logger.phase("act", {
                "iteration": iteration, "check": name, "path": case["path"], "payload": payload,
            })
            body = None
            retryable = False
            try:
                body = post_json(args.base_url.rstrip("/") + case["path"], payload, HTTP_TIMEOUT)
                issues = (
                    check_mcp(body, payload) if args.mode == "mcp"
                    else check_rag(body, refuse=name == "unrelated_refusal")
                )
            except error.HTTPError as exc:
                issues = [f"Backend returned HTTP {exc.code}."]
                retryable = exc.code >= 500 or exc.code == 429
            except (error.URLError, TimeoutError, OSError) as exc:
                issues = [f"Backend request failed: {exc}"]
                retryable = True
            except (ValueError, UnicodeDecodeError) as exc:
                issues = [f"Invalid backend response: {exc}"]
            results[name] = {
                "passed": not issues, "attempts": iteration, "issues": issues, "response": body,
            }
            logger.phase("observe", {"iteration": iteration, "check": name, **results[name]})
            if issues and retryable and iteration < MAX_ATTEMPTS:
                retry.append(case)
        failed = [name for name, result in results.items() if not result["passed"]]
        logger.phase("adapt", {
            "iteration": iteration,
            "decision": "retry_unavailable_checks" if retry else ("fail" if failed else "pass"),
            "retry_checks": [case["name"] for case in retry],
            "failed_checks": failed,
            "guidance": (
                "Check service URLs, feature flags, seeded catalogue and the RAG source sync; "
                "fix failing contracts before rerunning."
                if failed else "All requested response checks passed."
            ),
        })
        if not retry:
            break
        pending = retry
        time.sleep(1)
    return {
        "run_id": run_id,
        "mode": args.mode,
        "base_url": args.base_url,
        "passed": all(result["passed"] for result in results.values()),
        "checks": results,
        "transcript": logger.transcript_path,
        "scope": "Live backend response validation; answer factual accuracy still needs review.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("mcp", "rag"), required=True)
    parser.add_argument("--base-url", default="http://localhost:3000/almanac")
    parser.add_argument("--log-dir", type=Path, help="directory for private validation transcripts")
    parser.add_argument("--output", type=Path, help="also save the JSON result to this file")
    args = parser.parse_args()
    if urlparse(args.base_url).scheme not in ("http", "https"):
        parser.error("--base-url must be an http or https URL")
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    result = run(args)
    output = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output + "\n", encoding="utf-8")
    print(output)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Run a small, evidence-based AI review without changing project files."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


# Configuration

HERE = Path(__file__).resolve().parent
PROMPTS = HERE / "prompts"
FINDING_MODEL = "qwen3:4b-instruct"
REVIEW_MODEL = "llama3.1:8b"
MAX_CONTEXT_CHARS = 16_000

SCOPES = {
    "frontend": ("Frontend", ("shared/frontend/",)),
    "vgarden": ("Virtual Garden", ("vgarden/",)),
    "almanac": ("Plant Almanac", ("almanac/",)),
    "health": ("Plant Health", ("health/",)),
    "architecture": (
        "Whole project architecture",
        (
            ".github/workflows/",
            "ai-services/",
            "almanac/",
            "auth/",
            "docker-compose.yml",
            "docs/",
            "health/",
            "scripts/",
            "shared/",
            "vgarden/",
        ),
    ),
}

FEATURE_OBJECTIVE = """Review the selected feature and identify one small improvement.
Use only the supplied repository files. Do not invent missing behaviour or generate code.
State any limitation and recommend no more than two practical changes."""

ARCHITECTURE_OBJECTIVE = """Review the shared microservices architecture using only the
supplied repository files. Check which of the five student features are integrated, visible
service dependencies, missing or placeholder directories, the shared Ollama service, and the
shared containerised entry point. Separate evidence from assumptions, state limitations, and
recommend no more than two practical changes."""

ARCHITECTURE_PRIORITY = (
    "docker-compose.yml",
    "shared/frontend/templates/index.html",
    "shared/frontend/app.py",
    "shared/frontend/Dockerfile",
    "auth/app.py",
    "vgarden/app.py",
    "almanac/.keep",
    "health/.keep",
    "ai-services/ai-mode/.keep",
)

ALLOWED_SUFFIXES = {".css", ".html", ".js", ".json", ".md", ".py", ".txt", ".yml", ".yaml"}
EXCLUDED_PARTS = {".git", ".ai-dev-runs", ".venv", "venv", "__pycache__", "node_modules"}


class ReviewError(RuntimeError):
    """A problem that can be shown directly to the user."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", required=True, choices=SCOPES)
    return parser.parse_args()


def section(name: str) -> None:
    print(f"\n{'─' * 72}\n{name}\n{'─' * 72}", flush=True)


def repository_root() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=True,
        text=True,
        capture_output=True,
    )
    return Path(result.stdout.strip()).resolve()


def current_author(repo: Path) -> str:
    """Use the signed-in GitHub user, with local Git as an offline fallback."""
    commands = (
        ["gh", "api", "user", "--jq", ".name // .login"],
        ["git", "config", "user.name"],
    )
    for command in commands:
        try:
            result = subprocess.run(
                command,
                cwd=repo,
                text=True,
                capture_output=True,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    return "Unknown"


# Evidence collection

def is_discovery_path(path: str) -> bool:
    candidate = Path(path)
    if any(part in EXCLUDED_PARTS for part in candidate.parts):
        return False
    if candidate.name == ".env" or candidate.name.startswith(".env."):
        return False
    return candidate.name == ".keep" or candidate.suffix.lower() in ALLOWED_SUFFIXES


def path_in_scope(path: str, scope: str | None) -> bool:
    if scope is None:
        return True
    return any(path.startswith(prefix) for prefix in SCOPES[scope][1])


def read_inside_repo(path: Path, repo: Path) -> tuple[str, str]:
    resolved = (repo / path).resolve() if not path.is_absolute() else path.resolve()
    try:
        relative = resolved.relative_to(repo)
    except ValueError as exc:
        raise ReviewError(f"File is outside the repository: {path}") from exc
    if not resolved.is_file():
        raise ReviewError(f"File does not exist: {relative}")
    return relative.as_posix(), resolved.read_text(encoding="utf-8")


def discovery_paths(repo: Path, scope: str) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=repo,
        check=True,
        text=True,
        capture_output=True,
    )
    available = set(result.stdout.splitlines())
    scoped = {path for path in available if path_in_scope(path, scope)}

    if scope == "architecture":
        priority = [path for path in ARCHITECTURE_PRIORITY if path in available]
        ordered = priority + sorted(scoped - set(priority))
    else:
        shared = [
            path
            for path in ("docker-compose.yml", "README.md", "AGENTS.md")
            if path in available
        ]
        ordered = sorted(scoped) + shared

    selected: list[Path] = []
    used = 0
    for name in dict.fromkeys(ordered):
        path = repo / name
        if not is_discovery_path(name) or not path.is_file():
            continue
        try:
            size = len(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            continue
        if used + size > MAX_CONTEXT_CHARS:
            continue
        selected.append(Path(name))
        used += size
    return selected


def load_context(paths: list[Path], repo: Path) -> str:
    sections = []
    for path in paths:
        name, content = read_inside_repo(path, repo)
        sections.append(f"\n--- {name} ---\n{content}")
    return "".join(sections) or "\n(No reviewable files were found.)"


def reviewable_feature_paths(paths: list[Path], scope: str) -> list[Path]:
    return [
        path
        for path in paths
        if path_in_scope(path.as_posix(), scope) and path.name != ".keep"
    ]


# Local model calls

def call_model(model: str, system_prompt: str, user_prompt: str) -> str:
    request_body = {
        "model": model,
        "stream": False,
        "format": "json",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "options": {"temperature": 0.1, "num_ctx": 8192, "num_predict": 700},
    }
    request = urllib.request.Request(
        f"{os.getenv('OLLAMA_URL', 'http://localhost:11434').rstrip('/')}/api/chat",
        data=json.dumps(request_body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ReviewError(f"Ollama returned HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise ReviewError(f"Ollama request failed for {model}: {exc}") from exc

    output = (body.get("message") or {}).get("content")
    if not isinstance(output, str) or not output.strip():
        raise ReviewError(f"{model} returned no usable response")

    return output.strip()


def parse_json_object(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    for start, character in enumerate(text):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ReviewError("The model did not return a JSON object")


def validate_finding(finding: dict[str, Any], paths: list[Path], scope: str | None) -> None:
    for key in ("title", "summary", "recommendation"):
        if not isinstance(finding.get(key), str) or not finding[key].strip():
            raise ReviewError(f"The recommendation has no usable {key}")

    inspected = {path.as_posix() for path in paths}
    evidence = finding.get("evidence")
    recommendations = finding.get("file_recommendations")
    checks = finding.get("checks")

    if not isinstance(evidence, list) or not 1 <= len(evidence) <= 3:
        raise ReviewError("The recommendation must cite one to three inspected files")
    if not isinstance(recommendations, list) or not 1 <= len(recommendations) <= 2:
        raise ReviewError("The recommendation must name one or two files")
    if not isinstance(checks, list) or not 1 <= len(checks) <= 3:
        raise ReviewError("The recommendation must include one to three checks")

    for item in evidence:
        if not isinstance(item, dict) or item.get("path") not in inspected:
            raise ReviewError("Evidence must cite an inspected file")
        if not isinstance(item.get("observation"), str):
            raise ReviewError("Each evidence item needs a clear observation")
    for item in recommendations:
        path = item.get("path") if isinstance(item, dict) else None
        if path not in inspected or (scope and not path_in_scope(path, scope)):
            raise ReviewError("Recommendations must stay within inspected files")
        if not isinstance(item.get("suggestion"), str):
            raise ReviewError("Each recommended file needs a clear suggestion")


def normalise_review(review: dict[str, Any]) -> dict[str, Any]:
    status = str(review.get("status", "revise")).lower()
    if status not in {"supported", "revise"}:
        status = "revise"
    findings = review.get("findings", [])
    if not isinstance(findings, list):
        findings = [findings]
    clean_findings = []
    for item in findings:
        if isinstance(item, dict):
            item = item.get("summary") or item.get("finding") or ""
        if str(item).strip():
            clean_findings.append(str(item).strip())
    return {
        "status": status,
        "summary": str(review.get("summary", "No review summary returned.")),
        "findings": clean_findings,
    }


# Human check and reports

def ask_human_decision(
    input_fn: Callable[[str], str] = input,
    *,
    interactive: bool | None = None,
) -> dict[str, str | None]:
    if interactive is None:
        interactive = sys.stdin.isatty()
    if not interactive:
        raise ReviewError("A human must accept or reject the recommendation")

    while True:
        try:
            choice = input_fn("Accept or reject? [a/r]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            raise ReviewError("No human decision was recorded")
        if choice not in {"a", "accept", "r", "reject"}:
            print("Please enter a or r.")
            continue
        status = "accepted" if choice in {"a", "accept"} else "rejected"
        try:
            note = input_fn("Optional note (press Enter to skip): ").strip() or None
        except (EOFError, KeyboardInterrupt):
            note = None
        return {"decision": status, "note": note}


def author_slug(author: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", author.lower()).strip("_") or "unknown"


def create_output_paths(
    repo: Path, target: str, author: str
) -> tuple[int, Path, Path]:
    log_dir = repo / "tools" / "ai-dev" / "logs"
    slug = author_slug(author)
    reports_dir = log_dir / "reports" / slug
    reports_dir.mkdir(parents=True, exist_ok=True)
    existing_ids = [
        int(path.name.split("-", 1)[0])
        for path in reports_dir.glob("[0-9]*-*.md")
        if path.name.split("-", 1)[0].isdigit()
    ]
    report_id = max(existing_ids, default=0) + 1
    target_slug = "-".join(target.lower().split())
    report_path = reports_dir / f"{report_id:04d}-{target_slug}.md"
    return report_id, log_dir / f"{slug}.md", report_path


def markdown_cell(value: Any) -> str:
    return " ".join(str(value).split()).replace("|", "\\|")


def one_sentence(value: Any) -> str:
    text = " ".join(str(value).split())
    end = text.find(".")
    return text[: end + 1] if end >= 0 else text


def write_review_files(
    report_id: int,
    log_path: Path,
    report_path: Path,
    *,
    target: str,
    context_paths: list[Path],
    finding: dict[str, Any],
    review: dict[str, Any],
    decision: dict[str, str | None],
    models: dict[str, str],
    author: str,
) -> Path:
    started = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    lines = [
        f"# AI review {report_id}: {target}",
        "",
        "| Date | Author | Proposer | Reviewer | Files changed |",
        "|---|---|---|---|---|",
        (
            f"| {started} | {markdown_cell(author)} | {markdown_cell(models['finding'])} | "
            f"{markdown_cell(models['review'])} | No |"
        ),
        "",
        "## Stage log",
        "",
        "| Stage | Result |",
        "|---|---|",
        f"| PLAN | Reviewed {len(context_paths)} repository files |",
        f"| ACT | {markdown_cell(finding['title'])} |",
        f"| OBSERVE | {markdown_cell(review['status'])} |",
        f"| ADAPT | {markdown_cell(decision['decision'])} |",
        "",
        "## Files reviewed",
        "",
        "| # | File |",
        "|---|---|",
    ]
    lines += [
        f"| {number} | `{markdown_cell(path.as_posix())}` |"
        for number, path in enumerate(context_paths, start=1)
    ]
    lines += [
        "",
        f"## {finding['title']}",
        "",
        str(finding["summary"]),
        "",
        str(finding["recommendation"]),
        "",
        "## Evidence",
        "",
        "| File | Observation |",
        "|---|---|",
    ]
    for item in finding.get("evidence", []):
        lines.append(f"| `{markdown_cell(item['path'])}` | {markdown_cell(item['observation'])} |")
    lines += ["", "## Recommended changes", "", "| File | Recommendation |", "|---|---|"]
    for item in finding.get("file_recommendations", []):
        lines.append(f"| `{markdown_cell(item['path'])}` | {markdown_cell(item['suggestion'])} |")
    lines += [
        "",
        "## Independent review",
        "",
        str(review.get("summary", "Not run.")),
    ]
    lines += [f"- {item}" for item in review.get("findings", [])]
    lines += [
        "",
        "## Human outcome",
        "",
        "| Outcome | Note |",
        "|---|---|",
        (
            f"| {markdown_cell(decision['decision'])} | "
            f"{markdown_cell(decision.get('note') or 'None')} |"
        ),
        "",
    ]
    report_path.write_text("\n".join(lines), encoding="utf-8")

    if not log_path.exists():
        log_path.write_text(
            f"# AI review index: {author}\n\n"
            "| ID | Scope | Author | File | Change | Status | Notes | Full report |\n"
            "|---|---|---|---|---|---|---|---|\n",
            encoding="utf-8",
        )
    file_links = "<br>".join(
        f"[`{markdown_cell(item['path'])}`](../../../{item['path']})"
        for item in finding["file_recommendations"]
    )
    report_link = f"[Open](reports/{author_slug(author)}/{report_path.name})"
    row = (
        f"| {report_id} | {markdown_cell(target)} | {markdown_cell(author)} | {file_links} | "
        f"{markdown_cell(one_sentence(finding['recommendation']))} | "
        f"{markdown_cell(decision['decision'])} | "
        f"{markdown_cell(decision.get('note') or '')} | {report_link} |\n"
    )
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(row)
    return report_path


# Plan -> Act -> Observe -> Adapt

def main() -> int:
    args = parse_args()
    repo = repository_root()
    target = SCOPES[args.scope][0]
    objective = ARCHITECTURE_OBJECTIVE if args.scope == "architecture" else FEATURE_OBJECTIVE
    models = {"finding": FINDING_MODEL, "review": REVIEW_MODEL}
    author = current_author(repo)

    section("PLAN")
    paths = discovery_paths(repo, args.scope)
    context = load_context(paths, repo)
    print(f"Target: {target}")
    print(f"Author: {author}")
    print(f"Evidence: {len(paths)} files ({len(context):,} characters)")
    print(f"Models: {FINDING_MODEL} proposes; {REVIEW_MODEL} checks")

    has_code = args.scope == "architecture" or bool(reviewable_feature_paths(paths, args.scope))
    if not has_code:
        section("RESULT")
        print("No implemented feature code was found. Nothing was added to the log.")
        return 0

    section("ACT")
    print(f"Asking {FINDING_MODEL} for one evidence-based recommendation.")
    finding = parse_json_object(
        call_model(
            FINDING_MODEL,
            (PROMPTS / "act.txt").read_text(encoding="utf-8"),
            f"OBJECTIVE\n{objective}\n\nEVIDENCE{context}",
        )
    )
    validate_finding(finding, paths, args.scope)
    print(f"Suggestion: {finding['title']}")
    print(finding["summary"])
    print(f"Recommendation: {finding['recommendation']}")
    for item in finding["file_recommendations"]:
        print(f"- {item['path']}: {item['suggestion']}")

    section("OBSERVE")
    print(f"Asking {REVIEW_MODEL} to check the evidence.")
    review = normalise_review(
        parse_json_object(
            call_model(
                REVIEW_MODEL,
                (PROMPTS / "observe.txt").read_text(encoding="utf-8"),
                f"OBJECTIVE\n{objective}\n\nFINDING\n{json.dumps(finding)}\n\nEVIDENCE{context}",
            )
        )
    )
    print(f"Reviewer result: {review['status']}")
    print(review["summary"])
    for item in review["findings"]:
        print(f"- {item}")

    section("ADAPT")
    print("Record whether the recommendation is useful. Project files stay unchanged.")
    decision = ask_human_decision()

    report_id, log_path, report_path = create_output_paths(repo, target, author)
    write_review_files(
        report_id,
        log_path,
        report_path,
        target=target,
        context_paths=paths,
        finding=finding,
        review=review,
        decision=decision,
        models=models,
        author=author,
    )
    section("RESULT")
    print(f"Outcome: {decision['decision']}")
    print(f"Full report: {report_path}")
    print(f"Index: {log_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ReviewError, subprocess.CalledProcessError) as exc:
        print(f"AI review failed: {exc}")
        raise SystemExit(1) from exc

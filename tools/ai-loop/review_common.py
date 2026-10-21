"""Helpers shared by the Release 2 review-mode modules of `review.py`.

Markdown rendering for the validation logs, the loop-trace table, the copies a
mode writes next to the evidence, and the one http(s) GET the Multi-Agent mode
uses to read a live server. Standard library only.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from urllib import error, request

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_ROOT = ROOT / "docs" / "evidence" / "release2"
# Where the Multi-Agent and Testing review modes copy their validation logs.
DEFAULT_COPY_DIR = EVIDENCE_ROOT / "agentic-review"
MODEL_TIMEOUT = 180  # one local model call; the same bound the health service uses

DECISIONS = ("pass", "pass_with_findings", "fail", "insufficient_evidence")
SEVERITIES = ("high", "medium", "low")
MAX_FINDINGS = 12
MAX_FIELD_CHARS = 300
MAX_RECOMMENDATIONS = 8

DECISION_MEANINGS = (
    "`pass` = every required check holds (low findings, if any, are informational); "
    "`pass_with_findings` = the evidence stands but the medium findings should be addressed "
    "before the report is finalised; `fail` = at least one high finding, the evidence does "
    "not show what it must; `insufficient_evidence` = nothing reviewable was found, "
    "regenerate the evidence. Only a check computed in code can be high or medium."
)


def clip(value, limit: int = MAX_FIELD_CHARS) -> str:
    return " ".join(str(value if value is not None else "").split())[:limit]


def md_cell(value) -> str:
    return " ".join(str(value if value is not None else "").split()).replace("|", "\\|")


def md_table(headers: list[str], rows: list[list]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    for row in rows:
        lines.append("| " + " | ".join(md_cell(cell) for cell in row) + " |")
    return "\n".join(lines)


def shown_path(path: Path | str) -> str:
    try:
        return Path(path).resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def decision_from_findings(findings: list[dict]) -> str:
    """The rule every review mode applies whatever the model said: a high finding
    fails, a medium finding passes with findings, low findings are informational."""
    severities = {finding["severity"] for finding in findings}
    if "high" in severities:
        return "fail"
    if "medium" in severities:
        return "pass_with_findings"
    return "pass"


def loop_verdict_label(verdict: str) -> str:
    return {
        "approved": "approved by the independent reviewer",
        "revised_capped": "iteration cap reached without reviewer approval; read the OBSERVE issues below",
        "fallback": "single-shot, no reviewer (see the FALLBACK row)",
    }.get(verdict, verdict)


def trace_rows(trace: list[dict], plan: dict) -> list[list]:
    rows = []
    for event in trace:
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
        rows.append([phase.upper(), event.get("iteration", ""), outcome, event.get("elapsed_ms", "")])
    return rows


def findings_table(findings: list[dict], subject_header: str, subject_key: str, kind_key: str) -> str:
    if not findings:
        return "_No findings._"
    return md_table(
        ["#", "Severity", kind_key.replace("_", " ").title(), subject_header, "Evidence", "Recommendation"],
        [
            [i, f["severity"], f[kind_key], f.get(subject_key) or "*", f["evidence"], f["recommendation"]]
            for i, f in enumerate(findings, start=1)
        ],
    )


def corrections_md(corrections: list[str]) -> str:
    if corrections:
        return "\n".join(f"- {note}" for note in corrections)
    return "_None: the final draft already satisfied every review rule._"


def recommendations_md(recommendations: list[str]) -> str:
    if recommendations:
        return "\n".join(f"{i}. {text}" for i, text in enumerate(recommendations, start=1))
    return "_None._"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def stamp_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def write_copies(copy_dir: Path, prefix: str, stamp: str, log_md: str, summary: dict) -> dict:
    """Write `<prefix>-<stamp>-review.md/.json` plus `<prefix>-latest-review.*` into
    `copy_dir`; returns the paths (also stored in summary["validation_log"])."""
    copy_dir.mkdir(parents=True, exist_ok=True)
    md_path = copy_dir / f"{prefix}-{stamp}-review.md"
    json_path = copy_dir / f"{prefix}-{stamp}-review.json"
    summary["validation_log"] = {"markdown": str(md_path), "json": str(json_path)}
    md_path.write_text(log_md, encoding="utf-8")
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for latest, source in ((f"{prefix}-latest-review.md", md_path), (f"{prefix}-latest-review.json", json_path)):
        (copy_dir / latest).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    return summary["validation_log"]


def http_get(url: str, timeout: int = 30) -> bytes:
    """GET a local http(s) URL (the Multi-Agent Server's audit export)."""
    if not url.startswith(("http://", "https://")):
        raise ValueError("--server must be an http or https URL")
    try:
        with request.urlopen(url, timeout=timeout) as response:  # noqa: S310 -- scheme checked above; operator-set URL
            return response.read()
    except error.HTTPError as exc:
        raise SystemExit(f"The Multi-Agent Server answered HTTP {exc.code} for {url}") from exc
    except (error.URLError, TimeoutError, OSError) as exc:
        raise SystemExit(f"Could not reach the Multi-Agent Server at {url}: {exc}") from exc


def read_jsonl(text: str) -> tuple[list[dict], int]:
    """Parse JSON Lines; returns (rows, skipped) where skipped counts unparseable lines."""
    rows, skipped = [], 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            skipped += 1
            continue
        if isinstance(row, dict):
            rows.append(row)
        else:
            skipped += 1
    return rows, skipped


def validate_common(raw, *, count_key: str, kind_key: str, kinds: tuple, subject_key: str) -> list[str]:
    """Schema check in code shared by the review modes: the model's output is untrusted."""
    problems = []
    if not isinstance(raw, dict):
        return ["decision must be a JSON object"]
    if raw.get("decision") not in DECISIONS:
        problems.append(f"decision must be one of {', '.join(DECISIONS)}")
    if type(raw.get(count_key)) is not int or raw[count_key] < 0:
        problems.append(f"{count_key} must be a non-negative integer")
    if not isinstance(raw.get("summary"), str) or not raw["summary"].strip():
        problems.append("summary must be a non-empty string")
    recommendations = raw.get("recommendations")
    if not isinstance(recommendations, list) or any(not isinstance(r, str) for r in recommendations):
        problems.append("recommendations must be a list of strings")
    findings = raw.get("findings")
    if not isinstance(findings, list):
        problems.append("findings must be a list")
        return problems
    for index, finding in enumerate(findings):
        if not isinstance(finding, dict):
            problems.append(f"findings[{index}] must be an object")
            continue
        if finding.get("severity") not in SEVERITIES:
            problems.append(f"findings[{index}].severity must be high, medium or low")
        if finding.get(kind_key) not in kinds:
            problems.append(f"findings[{index}].{kind_key} must be one of {', '.join(kinds)}")
        if not isinstance(finding.get(subject_key), str):
            problems.append(f"findings[{index}].{subject_key} must be a string")
        for key in ("evidence", "recommendation"):
            if not isinstance(finding.get(key), str) or not finding[key].strip():
                problems.append(f"findings[{index}].{key} must be a non-empty string")
    return problems


def merge_code_findings(
    model_findings: list[dict],
    code_findings: list[dict],
    *,
    kind_key: str,
    subject_key: str,
    known_subjects: set[str],
    corrections: list[str],
    aliases: dict[str, str] | None = None,
) -> list[dict]:
    """The findings are the code checks. A model finding is kept only when the
    code computed the same violation (same kind and subject): it then carries the
    model's wording and recommendation but the code's severity. A model finding
    the code did not confirm is dropped: every check kind is decided in code, so
    the grounding contradicts it. Every code finding the model left out is added,
    first. `aliases` maps other identifiers the model may use for a subject (run
    ids, for workflows) onto the subject itself."""
    aliases = aliases or {}
    code_by_key = {(f[kind_key], f[subject_key]): f for f in code_findings}
    kept: dict[tuple, dict] = {}
    for finding in model_findings:
        subject = clip(finding.get(subject_key) or "*", 80) or "*"
        evidence = clip(finding["evidence"])
        if subject in aliases and subject not in known_subjects:
            corrections.append(f"mapped {subject_key} '{subject[:12]}' (a run id) to its workflow '{aliases[subject][:12]}'")
            subject = aliases[subject]
        if subject != "*" and subject not in known_subjects:
            corrections.append(f"dropped finding '{evidence[:80]}': {subject_key} '{subject}' is not in the grounding")
            continue
        key = (finding[kind_key], subject)
        code = code_by_key.get(key)
        if code is None:
            corrections.append(
                f"dropped finding '{evidence[:80]}': the {finding[kind_key]} check holds for {subject} in the "
                "grounding, so nothing confirms it"
            )
            continue
        if key in kept:
            corrections.append(f"dropped duplicate finding '{evidence[:80]}' ({finding[kind_key]} for {subject})")
            continue
        if finding["severity"] != code["severity"]:
            corrections.append(
                f"severity of {finding[kind_key]} for {subject} set to {code['severity']} (code check), "
                f"the draft said {finding['severity']}"
            )
        kept[key] = {
            "severity": code["severity"],
            kind_key: finding[kind_key],
            subject_key: subject,
            "evidence": evidence,
            "recommendation": clip(finding["recommendation"]),
        }
    added = []
    for finding in code_findings:
        key = (finding[kind_key], finding[subject_key])
        if key in kept or any((a[kind_key], a[subject_key]) == key for a in added):
            continue
        corrections.append(f"added the missing {finding['severity']} finding {finding[kind_key]} for {finding[subject_key]}")
        added.append(dict(finding))
    findings = added + list(kept.values())
    if len(findings) > MAX_FINDINGS:
        corrections.append(f"findings cut to the first {MAX_FINDINGS}")
    return findings[:MAX_FINDINGS]


def finish_decision(raw: dict, findings: list[dict], corrections: list[str], *, fallback_recommendation: str) -> dict:
    """Apply the decision rule, clip the prose and prefix the summary when the code
    overruled the model's decision or removed findings it had invented."""
    decision = decision_from_findings(findings)
    if raw.get("decision") == "insufficient_evidence":
        corrections.append("insufficient_evidence without an evidence gap -> decided from the findings")
    elif raw.get("decision") != decision:
        corrections.append(f"{raw.get('decision')} is inconsistent with the findings -> {decision}")
    recommendations = [clip(r, 400) for r in raw.get("recommendations", []) if clip(r, 400)]
    recommendations = list(dict.fromkeys(recommendations))[:MAX_RECOMMENDATIONS]
    if findings and not recommendations:
        corrections.append("added the fallback recommendation: the draft had none despite findings")
        recommendations = [fallback_recommendation]
    summary = clip(raw.get("summary"), 600)
    dropped = sum(1 for note in corrections if note.startswith("dropped finding"))
    if raw.get("decision") != decision:
        reasons = [f["evidence"] for f in findings if f["severity"] == "high"] or [
            f["evidence"] for f in findings if f["severity"] == "medium"
        ]
        summary = clip(
            f"Corrected in code to {decision}: "
            + ("; ".join(reasons[:3]) if reasons else "no code check supports a different decision")
            + f". The model's draft said: {summary}",
            600,
        )
    if dropped:
        summary = clip(
            f"{dropped} finding(s) in the model's draft were not confirmed by the code checks and were "
            f"removed (see the corrections); read its prose with that in mind. {summary}",
            700,
        )
    return {"decision": decision, "findings": findings, "recommendations": recommendations, "summary": summary}

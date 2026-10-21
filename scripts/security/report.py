"""Scan whole services and write a summary of the results that is safe to commit.

The commit hooks only scan staged files and keep their raw output in the
git-ignored .security-reports/ folder. This script runs the same four checks
(through run_checks.py) over every tracked file of the named services, then writes
a Markdown summary with pass/fail and counts only. It never copies raw scan
output, so no flagged secret or file content ends up in the summary.

    python3 scripts/security/report.py vgarden auth \\
        --owner "Yunus Sayed" --out docs/evidence/release2/pre-commit-yunus.md
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / ".security-reports"
CHECKS = ("ruff", "secrets", "audit", "tests")
TESTED = ("almanac", "health", "vgarden", "auth")
EVIDENCE = re.compile(r"evidence: (\S+\.json)")


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()  # noqa: S603, S607 -- fixed Git query


def run_check(mode, names):
    """Run one check through run_checks.py and return its saved evidence."""
    result = subprocess.run(  # noqa: S603 -- our own script, fixed arguments, no shell
        [sys.executable, str(ROOT / "scripts/security/run_checks.py"), mode, *names],
        cwd=ROOT,
        env={**os.environ, "SECURITY_TRIGGER": "report"},
        text=True,
        capture_output=True,
    )
    match = EVIDENCE.search(result.stdout)
    if not match:
        sys.exit(f"{mode} did not save evidence:\n{result.stdout}{result.stderr}")
    return json.loads((ROOT / match.group(1)).read_text()), match.group(1)


def summarise(report):
    """One line of counts for a saved report. Never includes raw findings."""
    scan, stdout = report["scan"], report["stdout"]
    if scan == "ruff":
        findings = json.loads(stdout or "[]")
        rules = sorted({finding["code"] for finding in findings})
        return f"{len(findings)} findings" + (f" ({', '.join(rules)})" if rules else "")
    if scan == "secrets":
        flagged = len(re.findall(r"^Secret Type:", stdout, re.MULTILINE))
        return "no new secrets" if report["exit_code"] == 0 else f"{flagged or 'some'} flagged"
    if scan == "audit":
        dependencies = json.loads(stdout or "{}").get("dependencies", [])
        vulnerable = [d for d in dependencies if d.get("vulns")]
        return f"{len(dependencies)} packages, {len(vulnerable)} with known vulnerabilities"
    if scan == "tests":
        lines = [line for line in stdout.splitlines() if re.search(r"\d+ (passed|failed|errors?)", line)]
        return lines[-1].strip() if lines else "no pytest summary"
    return ""


def scope(report):
    if report["scan"] == "audit":
        return ", ".join(report["files"])
    if report["scan"] == "tests":
        return report["files"][0]
    return f"{len(report['files'])} files"


def full_scan(services):
    rows = []
    for service in services:
        tracked = git("ls-files", service).splitlines()
        python = [name for name in tracked if name.endswith(".py")]
        plan = [("ruff", python), ("secrets", tracked), ("audit", [service])]
        if service in TESTED:
            plan.append(("tests", [service]))
        for mode, names in plan:
            report, path = run_check(mode, names)
            rows.append((service, report, path))
            print(f"{service:8} {mode:8} {'PASS' if report['exit_code'] == 0 else 'FAIL'}")
    return rows


def hook_runs(services):
    """Group the hook's own saved reports by the commit tree they checked."""
    runs = {}
    for path in sorted(REPORTS.glob("*.json")):
        report = json.loads(path.read_text())
        if report.get("scan") not in CHECKS or report.get("trigger", "hook") != "hook":
            continue
        touched = report["files"] if report["scan"] != "tests" else report["files"][:1]
        if not any(name.startswith(service) for service in services for name in touched):
            continue
        runs.setdefault(report["index_tree"], {})[report["scan"]] = report
    commits = {}  # oldest commit per tree: the one the hooks checked, not a later merge
    for line in git("log", "--all", "--format=%H %T %s", "-200").splitlines():
        sha, tree, subject = line.split(" ", 2)
        commits[tree] = (sha[:7], subject)
    rows = []
    for tree, reports in runs.items():
        if tree not in commits or len(reports) < len(CHECKS):
            continue  # an aborted or uncommitted attempt
        sha, subject = commits[tree]
        rows.append((reports["ruff"]["started_at"][:16].replace("T", " "), sha, subject, reports))
    return sorted(rows)


def write(out, owner, services, scan_rows, commit_rows):
    status = "PASS" if all(r["exit_code"] == 0 for _, r, _ in scan_rows) else "FAIL"
    head = git("rev-parse", "--short", "HEAD")
    lines = [
        f"# Pre-commit security evidence: {owner}",
        "",
        f"Services: {', '.join(f'`{s}`' for s in services)}. Generated "
        f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} on "
        f"`{git('branch', '--show-current')}` at `{head}` by "
        "`scripts/security/report.py`. Overall: **" + status + "**.",
        "",
        "The hooks in `.pre-commit-config.yaml` run four checks on every commit:",
        "Ruff security rules (`--select S`), detect-secrets against `.secrets.baseline`,",
        "pip-audit on the service requirements, and the service's pytest suite. Raw output",
        "stays in the git-ignored `.security-reports/` folder; this page lists counts",
        "only.",
        "",
        "## Full scan of every tracked file",
        "",
        "| Service | Check | Scope | Result | Summary | Local evidence file |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for service, report, path in scan_rows:
        result = "PASS" if report["exit_code"] == 0 else "FAIL"
        lines.append(
            f"| `{service}` | {report['scan']} | {scope(report)} | {result} | "
            f"{summarise(report)} | `{path}` |"
        )
    if commit_rows:
        lines += [
            "",
            "## Hook runs on real commits",
            "",
            "Each row is one `git commit` that the hooks checked and let through.",
            "",
            "| When (UTC) | Commit | Ruff | Secrets | Audit | Tests |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for when, sha, subject, reports in commit_rows:
            cells = " | ".join(summarise(reports[check]) for check in CHECKS)
            lines.append(f"| {when} | `{sha}` {subject} | {cells} |")
    lines += [
        "",
        "## Reproduce",
        "",
        "```sh",
        f"python3 scripts/security/install.py {services[0]}   # tools + hook, once",
        f"python3 scripts/security/report.py {' '.join(services)} --owner \"{owner}\" --out {out}",
        "```",
        "",
    ]
    (ROOT / out).parent.mkdir(parents=True, exist_ok=True)
    (ROOT / out).write_text("\n".join(lines))
    return status


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("services", nargs="+")
    parser.add_argument("--owner", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    for service in args.services:
        if not (ROOT / service).is_dir():
            sys.exit(f"No such service: {service}")
    status = write(
        args.out, args.owner, args.services, full_scan(args.services), hook_runs(args.services)
    )
    print(f"{status}: wrote {args.out}")
    sys.exit(0 if status == "PASS" else 1)


if __name__ == "__main__":
    main()

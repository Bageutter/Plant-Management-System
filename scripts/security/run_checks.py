"""Run a commit check and retain local evidence."""

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
PYTHON = (
    ROOT / ".venv-security" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
)
GIT = shutil.which("git")
if not GIT:
    sys.exit("Git is required")
SERVICES = (
    "almanac",
    "health",
    "vgarden",
    "auth",
    "shared/frontend",
    "ai-services/mcp-server",
    "ai-services/rag-server",
    "ai-services/multi-agent-server",
)


def git(*args):
    return subprocess.check_output([GIT, *args], cwd=ROOT, text=True).strip()  # noqa: S603 -- fixed executable; no shell


def audit_targets(requested=()):
    changed = git("diff", "--cached", "--name-only").splitlines()
    selected = [service for service in requested if service in SERVICES] or [
        service for service in SERVICES if any(name.startswith(service + "/") for name in changed)
    ]
    if not selected:
        configured = subprocess.run(  # noqa: S603 -- fixed Git config query
            [GIT, "config", "--get", "security.service"], cwd=ROOT, text=True, capture_output=True
        ).stdout.strip()
        if configured not in SERVICES:
            raise ValueError("Run the security installer with your service name first")
        selected = [configured]
    return [
        service
        + (
            "/requirements-dev.txt"
            if (ROOT / service / "requirements-dev.txt").exists()
            else "/requirements.txt"
        )
        for service in selected
    ]


def main():
    if not PYTHON.exists():
        sys.exit("Install tools first: python3 scripts/security/install.py almanac")
    mode, *files = sys.argv[1:]
    working_directory = ROOT
    environment = None
    if mode == "ruff":
        files = [name for name in files if (ROOT / name).is_file() or (ROOT / name).is_dir()]
        if not files:
            sys.exit("No Python files selected")
        command = [
            str(PYTHON),
            "-m",
            "ruff",
            "check",
            "--select",
            "S",
            "--output-format",
            "json",
            *files,
        ]
    elif mode == "secrets":
        files = [name for name in files if (ROOT / name).is_file() and name != ".secrets.baseline"]
        command = [
            str(
                PYTHON.parent
                / ("detect-secrets-hook.exe" if sys.platform == "win32" else "detect-secrets-hook")
            ),
            "--no-verify",
            "--baseline",
            ".secrets.baseline",
            *files,
        ]
    elif mode == "audit":
        # Hooks pass no names; scripts/security/report.py names the services to audit.
        files = audit_targets(files)
        command = [str(PYTHON), "-m", "pip_audit", "--format", "json", "--progress-spinner", "off"]
        for filename in files:
            command.extend(["-r", filename])
    elif mode == "tests":
        # Hooks use the configured service; report.py may name one explicitly.
        service = files[0] if files else git("config", "--get", "security.service")
        if service not in ("almanac", "health", "vgarden", "auth"):
            sys.exit("Configure almanac, health, vgarden or auth for feature tests")
        python = (
            ROOT
            / ".venv-tests"
            / service
            / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        )
        if not python.exists():
            sys.exit(f"Install test dependencies: python3 scripts/security/install.py {service}")
        files = [service + "/tests"]
        command = [str(python), "-m", "pytest", "-q", "tests"]
        working_directory = ROOT / service
        environment = {
            **os.environ,
            "MCP_ENABLED": "false",
            "RAG_ENABLED": "false",
            "OLLAMA_PRELOAD": "false",
            "MULTI_AGENT_ENABLED": "false",
        }
    else:
        sys.exit("Choose ruff, secrets, audit or tests")
    started = datetime.now(timezone.utc)
    try:
        result = subprocess.run(  # noqa: S603 -- controlled commands and arguments, no shell
            command,
            cwd=working_directory,
            env=environment,
            text=True,
            capture_output=True,
            timeout=300,
        )
        code, stdout, stderr = result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        code, stdout, stderr = 1, "", "Check timed out after 300 seconds"
    directory = ROOT / ".security-reports"
    directory.mkdir(exist_ok=True)
    path = directory / f"{started.strftime('%Y%m%dT%H%M%SZ')}-{mode}-{uuid4().hex[:8]}.json"
    path.write_text(
        json.dumps(
            {
                "scan": mode,
                "trigger": os.environ.get("SECURITY_TRIGGER", "hook"),
                "started_at": started.isoformat(),
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "branch": git("branch", "--show-current"),
                "head": git("rev-parse", "HEAD"),
                "index_tree": git("write-tree"),
                "files": files,
                "exit_code": code,
                "command": command,
                "working_directory": str(working_directory),
                "stdout": stdout,
                "stderr": stderr,
            },
            indent=2,
        )
    )
    print(f"{mode}: {'PASS' if code == 0 else 'FAIL'}; evidence: {path.relative_to(ROOT)}")
    if code:
        # JSON Ruff output has locations/messages without source snippets.
        if mode == "ruff":
            try:
                for finding in json.loads(stdout):
                    print(
                        f"{Path(finding['filename']).relative_to(ROOT)}:{finding['location']['row']} {finding['code']} {finding['message']}"
                    )
            except (ValueError, KeyError):
                print("Read the local evidence file for scan diagnostics.")
        elif mode == "tests":
            print(stdout)
            print(stderr)
        else:
            print(
                "Read the local evidence file for findings. Do not share raw logs before reviewing them."
            )
    sys.exit(code)


if __name__ == "__main__":
    main()

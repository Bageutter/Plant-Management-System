"""Install this checkout's security tools and Git hook."""

import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
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


def main():
    if sys.version_info < (3, 10):
        sys.exit("Use Python 3.10 or newer; activate your feature virtual environment first")
    if len(sys.argv) != 2 or sys.argv[1] not in SERVICES:
        sys.exit("Usage: python3 scripts/security/install.py almanac|health|vgarden")
    location = ROOT / ".venv-security"
    if not location.exists():
        venv.create(location, with_pip=True)
    python = location / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    for command in (
        [str(python), "-m", "pip", "install", "-r", str(ROOT / "requirements-security.txt")],
        ["git", "config", "--local", "security.service", sys.argv[1]],
        [str(python), "-m", "pre_commit", "install"],
    ):
        subprocess.run(command, cwd=ROOT, check=True)  # noqa: S603 -- fixed install commands, no shell
    service = sys.argv[1]
    requirements = ROOT / service / "requirements-dev.txt"
    if service in ("almanac", "health", "vgarden", "auth"):
        tests_location = ROOT / ".venv-tests" / service
        if not tests_location.exists():
            venv.create(tests_location, with_pip=True)
        test_python = tests_location / (
            "Scripts/python.exe" if sys.platform == "win32" else "bin/python"
        )
        subprocess.run(  # noqa: S603 -- fixed dependency-install command, no shell
            [str(test_python), "-m", "pip", "install", "-r", str(requirements)],
            cwd=ROOT,
            check=True,
        )
    print("Installed. Security checks and assigned feature tests will run on git commit.")


if __name__ == "__main__":
    main()

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
    print("Installed. Security checks will run on git commit.")


if __name__ == "__main__":
    main()

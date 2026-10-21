"""Run each service's tests and save the evidence the Testing Review mode reads.

For every service it writes docs/evidence/release2/testing/<name>/:

  junit.xml    pytest's JUnit results
  pytest.txt   the full test log
  routes.json  every endpoint (Flask route, FastAPI-style app.get/post, MCP tool)
               and whether the tests ran its body, measured with coverage.py

An endpoint counts as tested only when coverage shows a line of its body ran
during the suite, not when a test file merely mentions its URL. AI services
are switched off, exactly as in the pre-commit hook and CI, so no model is
called.

    python3 scripts/test/collect-test-evidence.py              # every service
    python3 scripts/test/collect-test-evidence.py vgarden auth
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import venv
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "evidence" / "release2" / "testing"
SERVICES = (
    "vgarden",
    "auth",
    "almanac",
    "health",
    "shared/frontend",
    "ai-services/mcp-server",
    "ai-services/rag-server",
    "ai-services/multi-agent-server",
)
ENDPOINT_DECORATORS = {"route", "get", "post", "put", "patch", "delete", "custom_route", "tool"}
SKIP_DIRS = {"tests", "migrations", "__pycache__", "instance", "templates", "static", "evaluation", "sources"}
QUIET_ENV = {
    "MCP_ENABLED": "false",
    "RAG_ENABLED": "false",
    "MULTI_AGENT_ENABLED": "false",
    "AI_MODE_ENABLED": "false",
    "OLLAMA_PRELOAD": "false",
    "OLLAMA_AUTO_PULL": "false",
}


def slug(service: str) -> str:
    return service.rsplit("/", 1)[-1]


def run(command, **kwargs):
    return subprocess.run(command, text=True, capture_output=True, **kwargs)  # noqa: S603 -- fixed commands, no shell


def test_python(service: str) -> Path:
    """The service's own test environment (.venv-tests/<name>, shared with the hooks)."""
    location = ROOT / ".venv-tests" / slug(service)
    python = location / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    if not python.exists():
        print(f"  creating {location.relative_to(ROOT)}")
        venv.create(location, with_pip=True)
    requirements = ROOT / service / "requirements-dev.txt"
    if not requirements.exists():
        requirements = ROOT / service / "requirements.txt"
    marker = location / ".evidence-deps"
    wanted = requirements.read_text() if requirements.exists() else ""
    if not marker.exists() or marker.read_text() != wanted:
        args = [str(python), "-m", "pip", "install", "-q", "pytest", "coverage"]
        if requirements.exists():
            args += ["-r", str(requirements)]
        result = run(args, cwd=ROOT)
        if result.returncode:
            sys.exit(f"Could not install {service} test dependencies:\n{result.stderr[-2000:]}")
        marker.write_text(wanted)
    return python


def endpoints(service: str) -> list[dict]:
    """Find endpoint functions with the AST, so nothing has to be imported."""
    found = []
    base = ROOT / service
    for path in sorted(base.rglob("*.py")):
        rel = path.relative_to(base)
        if any(part in SKIP_DIRS or part.startswith(".") for part in rel.parts[:-1]) or rel.name == "conftest.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                call = decorator if isinstance(decorator, ast.Call) else None
                func = call.func if call else decorator
                if not (isinstance(func, ast.Attribute) and func.attr in ENDPOINT_DECORATORS):
                    continue
                route = None
                if call and call.args and isinstance(call.args[0], ast.Constant):
                    route = call.args[0].value
                methods = []
                for keyword in call.keywords if call else []:
                    if keyword.arg == "methods" and isinstance(keyword.value, (ast.List, ast.Tuple)):
                        methods = [e.value for e in keyword.value.elts if isinstance(e, ast.Constant)]
                if func.attr in ("get", "post", "put", "patch", "delete"):
                    methods = [func.attr.upper()]
                body = node.body
                if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant):
                    body = body[1:] or body  # skip the docstring
                found.append({
                    "kind": "mcp_tool" if func.attr == "tool" else "http",
                    "path": route if func.attr != "tool" else node.name,
                    "methods": methods or (["GET"] if func.attr != "tool" else []),
                    "function": f"{rel.with_suffix('').as_posix().replace('/', '.')}.{node.name}",
                    "file": f"{service}/{rel.as_posix()}",
                    "line": node.lineno,
                    "body_lines": [body[0].lineno, node.end_lineno],
                })
                break
    return found


def collect(service: str) -> dict:
    print(f"== {service}")
    out = OUT / slug(service)
    out.mkdir(parents=True, exist_ok=True)
    python = test_python(service)
    data_file = out / ".coverage"
    env = {**os.environ, **QUIET_ENV, "COVERAGE_FILE": str(data_file)}
    tests = "tests" if (ROOT / service / "tests").is_dir() else None
    started = datetime.now(timezone.utc)
    if tests:
        result = run([str(python), "-m", "coverage", "run", "--source=.", "-m", "pytest", "-q", "-p", "no:cacheprovider",
                      f"--junitxml={out / 'junit.xml'}", tests], cwd=ROOT / service, env=env, timeout=900)
        log, code = result.stdout + result.stderr, result.returncode
        json_report = out / "coverage.json"
        run([str(python), "-m", "coverage", "json", "-q", "-o", str(json_report)], cwd=ROOT / service, env=env)
        coverage = json.loads(json_report.read_text()) if json_report.exists() else {"files": {}, "totals": {}}
        json_report.unlink(missing_ok=True)
        data_file.unlink(missing_ok=True)
    else:
        log, code, coverage = "No tests/ folder: this service has no tests.\n", None, {"files": {}, "totals": {}}
        (out / "junit.xml").unlink(missing_ok=True)
    (out / "pytest.txt").write_text(log, encoding="utf-8")

    executed = {Path(name).as_posix(): set(info.get("executed_lines", [])) for name, info in coverage["files"].items()}
    routes = endpoints(service)
    for route in routes:
        local = route["file"][len(service) + 1:]
        first, last = route["body_lines"]
        route["tested"] = bool(executed.get(local, set()) & set(range(first, last + 1)))
    summary = {
        "service": service,
        "generated_at": started.isoformat(timespec="seconds"),
        "commit": run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT).stdout.strip(),
        "test_command": "coverage run -m pytest -q tests" if tests else None,
        "exit_code": code,
        "line_coverage_percent": round(coverage["totals"].get("percent_covered", 0.0), 1) if tests else None,
        "endpoints": len(routes),
        "endpoints_tested": sum(r["tested"] for r in routes),
        "routes": routes,
    }
    (out / "routes.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    status = "no tests" if code is None else ("PASS" if code == 0 else "FAIL")
    print(f"  {status}; {summary['endpoints_tested']}/{summary['endpoints']} endpoints exercised; "
          f"line coverage {summary['line_coverage_percent']}%")
    return summary


def main() -> int:
    wanted = sys.argv[1:] or list(SERVICES)
    unknown = [s for s in wanted if s not in SERVICES]
    if unknown:
        sys.exit(f"Unknown service(s): {', '.join(unknown)}. Choose from: {', '.join(SERVICES)}")
    failed = [s["service"] for s in map(collect, wanted) if s["exit_code"] not in (0, None)]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

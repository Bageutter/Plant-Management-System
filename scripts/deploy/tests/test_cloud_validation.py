"""Deployment regressions: fail before writes and keep evidence tied to its run.

Standard library only; no Azure, model calls or live application writes.
"""

import copy
import importlib.util
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

DEPLOY = Path(__file__).resolve().parents[1]


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, DEPLOY / filename)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


e2e = module("cloud_e2e", "azure-e2e.py")
report = module("cloud_report", "azure_report.py")


def baseline():
    flags = {mode: {"enabled": False} for mode in ("mcp", "rag", "multi_agent")}
    return {
        "/vgarden/integrations": copy.deepcopy(flags),
        "/almanac/integrations": copy.deepcopy(flags),
        "/health/plant-health-records/integrations": {**copy.deepcopy(flags), "ai_mode": {"enabled": False}},
    }


class BaselineTests(unittest.TestCase):
    def setUp(self):
        e2e.results.clear()

    def test_each_feature_must_explicitly_report_every_mode_disabled(self):
        bodies = baseline()
        def get(path, accept):
            return 200, json.dumps(bodies[path])
        self.assertIn("Health AI-Mode off", e2e.validate_baseline(get))
        for path, body in bodies.items():
            for mode in body:
                for invalid in ({"enabled": True}, {"enabled": "false"}, {}, None):
                    with self.subTest(path=path, mode=mode, invalid=invalid):
                        changed = copy.deepcopy(bodies)
                        changed[path][mode] = invalid
                        with self.assertRaises(AssertionError):
                            e2e.validate_baseline(lambda p, a: (200, json.dumps(changed[p])))

    def test_missing_mode_or_non_200_never_counts_as_disabled(self):
        bodies = baseline()
        del bodies["/almanac/integrations"]["rag"]
        with self.assertRaises(AssertionError):
            e2e.validate_baseline(lambda p, a: (200, json.dumps(bodies[p])))
        with self.assertRaises(AssertionError):
            e2e.validate_baseline(lambda p, a: (503, "{}"))

    def test_failed_preflight_never_bootstraps_account_and_writes_failure_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "crud.json"
            with patch.object(e2e, "validate_baseline", side_effect=AssertionError("AI enabled")), \
                 patch.object(e2e.VgardenSession, "bootstrap") as bootstrap, \
                 patch("sys.argv", ["azure-e2e.py", "https://cloud.invalid", "--json-out", str(output)]):
                self.assertEqual(e2e.main(), 1)
            bootstrap.assert_not_called()
            saved = json.loads(output.read_text())
            self.assertEqual(saved["result"], "fail")
            self.assertEqual(saved["passed"], 0)
            self.assertEqual(saved["total"], 1)


class ReportTests(unittest.TestCase):
    def test_report_does_not_reuse_another_run_or_targets_crud_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            facts, out = Path(tmp) / "facts", Path(tmp) / "out"
            facts.mkdir()
            out.mkdir()
            context = {"generated_at": "2026-10-22T10:00:00Z", "commit": "abc123",
                       "workflow_run_url": "https://github.invalid/actions/runs/42"}
            (facts / "context.json").write_text(json.dumps(context))
            (facts / "apps.json").write_text(json.dumps({"appUrl": {"value": "https://cloud.invalid"}}))
            crud = {"result": "pass", "commit": "abc123", "target": "https://cloud.invalid",
                    "workflow_run_url": context["workflow_run_url"], "generated_at": "2026-10-22T09:59:00Z"}
            for field, value in ((None, None), ("commit", "old"), ("workflow_run_url", "old-run"),
                                 ("target", "https://other.invalid"), ("generated_at", "2026-10-21T09:00:00Z")):
                with self.subTest(field=field):
                    saved = dict(crud)
                    if field:
                        saved[field] = value
                    (out / "e2e-crud.json").write_text(json.dumps(saved))
                    with patch.dict("os.environ", {"GITHUB_STEP_SUMMARY": ""}):
                        report.main(str(facts), str(out))
                    result = json.loads((out / "latest.json").read_text())
                    self.assertEqual(result["crud_test"]["result"], "unverified" if field else "pass")


class WorkflowTests(unittest.TestCase):
    def test_python_failure_survives_actual_workflow_tee_commands(self):
        workflow = (DEPLOY.parents[1] / ".github/workflows/cloud-deployment.yml").read_text()
        for name in ("Cloud baseline CRUD and persistence", "Cloud AI check (bonus profile)"):
            with self.subTest(step=name), tempfile.TemporaryDirectory() as tmp:
                section = workflow.split(f"      - name: {name}\n", 1)[1].split("      - name:", 1)[0]
                self.assertIn("shell: bash", section)
                command = section.split("        run: |\n", 1)[1]
                command = re.sub(r"\$\{\{.*?\}\}", "https://cloud.invalid", command)
                # Explicit Actions Bash uses -eo pipefail. Execute the actual run
                # block, replacing only the validator with a known failure.
                result = subprocess.run(  # noqa: S603 -- fixed Bash command and repository workflow, no user input
                    [shutil.which("bash"), "--noprofile", "--norc", "-eo", "pipefail", "-c",
                     "python3() { return 7; };\n" + command], cwd=tmp, capture_output=True,
                )
                self.assertEqual(result.returncode, 7, result.stderr.decode())


if __name__ == "__main__":
    unittest.main()

# Pre-commit security testing report — vgarden (Sample Student)

Generated 2026-10-21 08:00 UTC by `scripts/security/report.py` from the local evidence that
`scripts/security/run_checks.py` writes under `.security-reports/` each time a check runs
(the raw files stay local; this page carries the summary).

## Latest result per check

| Check | Result | Run (UTC) | Commit checked | Branch | Scope | Findings | Time |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Ruff security rules (`ruff check --select S`) | PASS | 2026-10-21 07:58 | `0a31150520` | `sample/branch` | 3 file(s) | no security findings | 0 s |
| detect-secrets (`detect-secrets-hook --baseline .secrets.baseline`) | PASS | 2026-10-21 07:58 | `0a31150520` | `sample/branch` | 12 file(s) | no new secrets outside the baseline | 1 s |
| pip-audit (dependency vulnerabilities) | PASS | 2026-10-21 07:59 | `0a31150520` | `sample/branch` | vgarden/requirements-dev.txt | 40 package(s) resolved, 0 with known vulnerabilities | 30 s |
| Assigned feature unit tests (pytest) | PASS | 2026-10-21 07:59 | `0a31150520` | `sample/branch` | vgarden/tests | 41 passed in 12.00s | 14 s |

**Overall:** all four checks passed on the latest run of each check.

## Every recorded run

| Run (UTC) | Check | Result | Commit | Branch | Findings |
| --- | --- | --- | --- | --- | --- |
| 2026-10-21 07:30:00 | ruff | FAIL | `0a31150520` | `sample/branch` | 2 finding(s): S310×2 |
| 2026-10-21 07:58:00 | ruff | PASS | `0a31150520` | `sample/branch` | no security findings |
| 2026-10-21 07:58:01 | secrets | PASS | `0a31150520` | `sample/branch` | no new secrets outside the baseline |
| 2026-10-21 07:59:00 | audit | PASS | `0a31150520` | `sample/branch` | 40 package(s) resolved, 0 with known vulnerabilities |
| 2026-10-21 07:59:30 | tests | PASS | `0a31150520` | `sample/branch` | 41 passed in 12.00s |

## What each check covers

- **Ruff security rules** — Bandit-derived `S` rules over the staged Python files.
- **detect-secrets** — scans the staged files for credential-like strings against `.secrets.baseline`.
- **pip-audit** — resolves `vgarden/requirements-dev.txt` and checks every package against the PyPI advisory database.
- **Assigned feature unit tests** — `pytest` for `vgarden/tests` with the AI services disabled.

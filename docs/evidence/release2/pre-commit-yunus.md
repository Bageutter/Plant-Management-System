# Pre-commit security evidence: Yunus Sayed

Services: `vgarden`, `auth`. Generated 2026-10-21 09:43 UTC on `yunz/release2-evidence` at `0a31150` by `scripts/security/report.py`. Overall: **PASS**.

The hooks in `.pre-commit-config.yaml` run four checks on every commit:
Ruff security rules (`--select S`), detect-secrets against `.secrets.baseline`,
pip-audit on the service requirements, and the service's pytest suite. Raw output
stays in the git-ignored `.security-reports/` folder; this page lists counts
only.

## Full scan of every tracked file

| Service | Check | Scope | Result | Summary | Local evidence file |
| --- | --- | --- | --- | --- | --- |
| `vgarden` | ruff | 39 files | PASS | 0 findings | `.security-reports/20261021T094243Z-ruff-f1770939.json` |
| `vgarden` | secrets | 62 files | PASS | no new secrets | `.security-reports/20261021T094243Z-secrets-94257500.json` |
| `vgarden` | audit | vgarden/requirements-dev.txt | PASS | 53 packages, 0 with known vulnerabilities | `.security-reports/20261021T094244Z-audit-01a63301.json` |
| `vgarden` | tests | vgarden/tests | PASS | 137 passed in 11.05s | `.security-reports/20261021T094249Z-tests-0dd60043.json` |
| `auth` | ruff | 13 files | PASS | 0 findings | `.security-reports/20261021T094301Z-ruff-e509b916.json` |
| `auth` | secrets | 25 files | PASS | no new secrets | `.security-reports/20261021T094301Z-secrets-bbf9cb4f.json` |
| `auth` | audit | auth/requirements-dev.txt | PASS | 29 packages, 0 with known vulnerabilities | `.security-reports/20261021T094302Z-audit-8413474b.json` |
| `auth` | tests | auth/tests | PASS | 10 passed in 1.26s | `.security-reports/20261021T094307Z-tests-95ddff38.json` |

## Hook runs on real commits

Each row is one `git commit` that the hooks checked and let through.

| When (UTC) | Commit | Ruff | Secrets | Audit | Tests |
| --- | --- | --- | --- | --- | --- |
| 2026-10-20 16:50 | `e62cb1d` ci(vgarden): post-commit tests for two assigned endpoint functions (#74) | 0 findings | no new secrets | 53 packages, 0 with known vulnerabilities | 122 passed in 12.59s |
| 2026-10-20 17:34 | `9fb2563` feat(vgarden): Multi-Agent workflow with human review on each garden | 0 findings | no new secrets | 53 packages, 0 with known vulnerabilities | 135 passed in 10.92s |

## Reproduce

```sh
python3 scripts/security/install.py vgarden   # tools + hook, once
python3 scripts/security/report.py vgarden auth --owner "Yunus Sayed" --out docs/evidence/release2/pre-commit-yunus.md
```

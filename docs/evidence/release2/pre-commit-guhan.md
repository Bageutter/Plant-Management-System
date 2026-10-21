# Pre-commit security evidence: Guhan Sundar

Services: `health`. Generated 2026-10-21 11:56 UTC on `release2-evidence-on-main` at `f6cc21a` by `scripts/security/report.py`. Overall: **PASS**.

The hooks in `.pre-commit-config.yaml` run four checks on every commit:
Ruff security rules (`--select S`), detect-secrets against `.secrets.baseline`,
pip-audit on the service requirements, and the service's pytest suite. Raw output
stays in the git-ignored `.security-reports/` folder; this page lists counts
only.

## Full scan of every tracked file

| Service | Check | Scope | Result | Summary | Local evidence file |
| --- | --- | --- | --- | --- | --- |
| `health` | ruff | 28 files | PASS | 0 findings | `.security-reports\20261021T115508Z-ruff-0f8ac61c.json` |
| `health` | secrets | 52 files | PASS | no new secrets | `.security-reports\20261021T115509Z-secrets-cee8f5b5.json` |
| `health` | audit | health/requirements-dev.txt | PASS | 55 packages, 0 with known vulnerabilities | `.security-reports\20261021T115512Z-audit-d10aec7b.json` |
| `health` | tests | health/tests | PASS | 74 passed in 46.91s | `.security-reports\20261021T115555Z-tests-b4e4aee9.json` |

## Hook runs on real commits

Each row is one `git commit` that the hooks checked and let through.

| When (UTC) | Commit | Ruff | Secrets | Audit | Tests |
| --- | --- | --- | --- | --- | --- |
| 2026-10-21 07:12 | `c11bc73` ci(health): post-commit tests for two assigned endpoint functions (#73) | 0 findings | no new secrets | 54 packages, 0 with known vulnerabilities | 62 passed in 28.51s |

## Reproduce

```sh
python3 scripts/security/install.py health   # tools + hook, once
python3 scripts/security/report.py health --owner "Guhan Sundar" --out docs/evidence/release2/pre-commit-guhan.md
```

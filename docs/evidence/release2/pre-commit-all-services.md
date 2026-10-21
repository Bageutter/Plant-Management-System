# Pre-commit security evidence: all services

Services: `vgarden`, `auth`, `almanac`, `health`, `shared/frontend`, `ai-services/mcp-server`, `ai-services/rag-server`, `ai-services/multi-agent-server`. Generated 2026-10-21 10:40 UTC on `yunz/release2-evidence` at `48fcee1` by `scripts/security/report.py`. Overall: **FAIL**.

The hooks in `.pre-commit-config.yaml` run four checks on every commit:
Ruff security rules (`--select S`), detect-secrets against `.secrets.baseline`,
pip-audit on the service requirements, and the service's pytest suite. Raw output
stays in the git-ignored `.security-reports/` folder; this page lists counts
only.

## Full scan of every tracked file

| Service | Check | Scope | Result | Summary | Local evidence file |
| --- | --- | --- | --- | --- | --- |
| `vgarden` | ruff | 39 files | PASS | 0 findings | `.security-reports/20261021T103944Z-ruff-e97e526c.json` |
| `vgarden` | secrets | 62 files | PASS | no new secrets | `.security-reports/20261021T103944Z-secrets-0c6bea2b.json` |
| `vgarden` | audit | vgarden/requirements-dev.txt | PASS | 53 packages, 0 with known vulnerabilities | `.security-reports/20261021T103945Z-audit-bebc0d8d.json` |
| `vgarden` | tests | vgarden/tests | PASS | 137 passed in 10.82s | `.security-reports/20261021T103950Z-tests-7b5bcd84.json` |
| `auth` | ruff | 13 files | PASS | 0 findings | `.security-reports/20261021T104002Z-ruff-955c45df.json` |
| `auth` | secrets | 25 files | PASS | no new secrets | `.security-reports/20261021T104002Z-secrets-1ff1faa3.json` |
| `auth` | audit | auth/requirements-dev.txt | PASS | 29 packages, 0 with known vulnerabilities | `.security-reports/20261021T104002Z-audit-4093b8ad.json` |
| `auth` | tests | auth/tests | PASS | 10 passed in 1.28s | `.security-reports/20261021T104006Z-tests-1ac6e6aa.json` |
| `almanac` | ruff | 31 files | FAIL | 10 findings (S104, S310) | `.security-reports/20261021T104008Z-ruff-6a401bf7.json` |
| `almanac` | secrets | 59 files | PASS | no new secrets | `.security-reports/20261021T104008Z-secrets-ed7d0b40.json` |
| `almanac` | audit | almanac/requirements-dev.txt | PASS | 47 packages, 0 with known vulnerabilities | `.security-reports/20261021T104009Z-audit-ad64f2c0.json` |
| `almanac` | tests | almanac/tests | PASS | 74 passed in 5.73s | `.security-reports/20261021T104014Z-tests-a64a2279.json` |
| `health` | ruff | 25 files | FAIL | 4 findings (S101, S104, S608) | `.security-reports/20261021T104020Z-ruff-29615c69.json` |
| `health` | secrets | 47 files | PASS | no new secrets | `.security-reports/20261021T104020Z-secrets-6655c542.json` |
| `health` | audit | health/requirements-dev.txt | PASS | 52 packages, 0 with known vulnerabilities | `.security-reports/20261021T104021Z-audit-dfd86282.json` |
| `health` | tests | health/tests | FAIL | 60 errors in 1.11s | `.security-reports/20261021T104026Z-tests-4ef2df68.json` |
| `shared/frontend` | ruff | 1 files | FAIL | 2 findings (S104, S201) | `.security-reports/20261021T104028Z-ruff-1c75d824.json` |
| `shared/frontend` | secrets | 6 files | PASS | no new secrets | `.security-reports/20261021T104028Z-secrets-89580e08.json` |
| `shared/frontend` | audit | shared/frontend/requirements.txt | PASS | 7 packages, 0 with known vulnerabilities | `.security-reports/20261021T104028Z-audit-cdabd089.json` |
| `ai-services/mcp-server` | ruff | 15 files | FAIL | 5 findings (S105, S106, S107, S310, S603) | `.security-reports/20261021T104032Z-ruff-6b1b3c3d.json` |
| `ai-services/mcp-server` | secrets | 18 files | PASS | no new secrets | `.security-reports/20261021T104032Z-secrets-177dc3d7.json` |
| `ai-services/mcp-server` | audit | ai-services/mcp-server/requirements-dev.txt | PASS | 35 packages, 0 with known vulnerabilities | `.security-reports/20261021T104032Z-audit-5c48b76d.json` |
| `ai-services/rag-server` | ruff | 24 files | FAIL | 5 findings (S106, S107, S607) | `.security-reports/20261021T104037Z-ruff-18955f4a.json` |
| `ai-services/rag-server` | secrets | 32 files | PASS | no new secrets | `.security-reports/20261021T104037Z-secrets-bad3dd86.json` |
| `ai-services/rag-server` | audit | ai-services/rag-server/requirements-dev.txt | FAIL | 92 packages, 1 with known vulnerabilities | `.security-reports/20261021T104038Z-audit-b92c4676.json` |
| `ai-services/multi-agent-server` | ruff | 15 files | PASS | 0 findings | `.security-reports/20261021T104044Z-ruff-f6533d02.json` |
| `ai-services/multi-agent-server` | secrets | 20 files | PASS | no new secrets | `.security-reports/20261021T104044Z-secrets-6cb69c77.json` |
| `ai-services/multi-agent-server` | audit | ai-services/multi-agent-server/requirements.txt | PASS | 37 packages, 0 with known vulnerabilities | `.security-reports/20261021T104045Z-audit-c6262b95.json` |

## Hook runs on real commits

Each row is one `git commit` that the hooks checked and let through.

| When (UTC) | Commit | Ruff | Secrets | Audit | Tests |
| --- | --- | --- | --- | --- | --- |
| 2026-10-20 16:50 | `e62cb1d` ci(vgarden): post-commit tests for two assigned endpoint functions (#74) | 0 findings | no new secrets | 53 packages, 0 with known vulnerabilities | 122 passed in 12.59s |
| 2026-10-20 17:34 | `9fb2563` feat(vgarden): Multi-Agent workflow with human review on each garden | 0 findings | no new secrets | 53 packages, 0 with known vulnerabilities | 135 passed in 10.92s |
| 2026-10-21 10:08 | `48fcee1` feat: Release 2 agentic-loop review modes, pre-commit and local deployment evidence | 0 findings | no new secrets | 57 packages, 0 with known vulnerabilities | 137 passed in 14.85s |

## Reproduce

```sh
python3 scripts/security/install.py vgarden   # tools + hook, once
python3 scripts/security/report.py vgarden auth almanac health shared/frontend ai-services/mcp-server ai-services/rag-server ai-services/multi-agent-server --owner "all services" --out docs/evidence/release2/pre-commit-all-services.md
```

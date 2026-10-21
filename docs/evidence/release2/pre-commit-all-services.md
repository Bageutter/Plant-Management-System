# Pre-commit security evidence: Amy testing evidence refresh

Services: `vgarden`, `auth`, `almanac`, `health`, `shared/frontend`, `ai-services/mcp-server`, `ai-services/rag-server`, `ai-services/multi-agent-server`. Generated 2026-10-21 13:43 UTC on `amy/testing-fix` at `228fec3` by `scripts/security/report.py`. Overall: **PASS**.

The hooks in `.pre-commit-config.yaml` run four checks on every commit:
Ruff security rules (`--select S`), detect-secrets against `.secrets.baseline`,
pip-audit on the service requirements, and the service's pytest suite. Raw output
stays in the git-ignored `.security-reports/` folder; this page lists counts
only.

## Full scan of every tracked file

| Service | Check | Scope | Result | Summary | Local evidence file |
| --- | --- | --- | --- | --- | --- |
| `vgarden` | ruff | 39 files | PASS | 0 findings | `.security-reports/20261021T134207Z-ruff-b8863770.json` |
| `vgarden` | secrets | 62 files | PASS | no new secrets | `.security-reports/20261021T134207Z-secrets-d46f9e33.json` |
| `vgarden` | audit | vgarden/requirements-dev.txt | PASS | 54 packages, 0 with known vulnerabilities | `.security-reports/20261021T134209Z-audit-92be2449.json` |
| `vgarden` | tests | vgarden/tests | PASS | 137 passed in 11.55s | `.security-reports/20261021T134215Z-tests-a7bad7a4.json` |
| `auth` | ruff | 14 files | PASS | 0 findings | `.security-reports/20261021T134227Z-ruff-8339ed38.json` |
| `auth` | secrets | 26 files | PASS | no new secrets | `.security-reports/20261021T134227Z-secrets-012f2153.json` |
| `auth` | audit | auth/requirements-dev.txt | PASS | 30 packages, 0 with known vulnerabilities | `.security-reports/20261021T134228Z-audit-08845118.json` |
| `auth` | tests | auth/tests | PASS | 32 passed in 2.91s | `.security-reports/20261021T134232Z-tests-936357b2.json` |
| `almanac` | ruff | 35 files | PASS | 0 findings | `.security-reports/20261021T134236Z-ruff-094e85c6.json` |
| `almanac` | secrets | 69 files | PASS | no new secrets | `.security-reports/20261021T134236Z-secrets-5c88cf92.json` |
| `almanac` | audit | almanac/requirements-dev.txt | PASS | 49 packages, 0 with known vulnerabilities | `.security-reports/20261021T134237Z-audit-2182d88e.json` |
| `almanac` | tests | almanac/tests | PASS | 100 passed, 4 subtests passed in 8.01s | `.security-reports/20261021T134243Z-tests-27a1bd66.json` |
| `health` | ruff | 31 files | PASS | 0 findings | `.security-reports/20261021T134252Z-ruff-e2d55d66.json` |
| `health` | secrets | 57 files | PASS | no new secrets | `.security-reports/20261021T134253Z-secrets-e808fe54.json` |
| `health` | audit | health/requirements-dev.txt | PASS | 53 packages, 0 with known vulnerabilities | `.security-reports/20261021T134254Z-audit-443ec962.json` |
| `health` | tests | health/tests | PASS | 97 passed in 9.50s | `.security-reports/20261021T134300Z-tests-ba124ca3.json` |
| `shared/frontend` | ruff | 3 files | PASS | 0 findings | `.security-reports/20261021T134310Z-ruff-d22f3f4e.json` |
| `shared/frontend` | secrets | 8 files | PASS | no new secrets | `.security-reports/20261021T134310Z-secrets-b9246c5c.json` |
| `shared/frontend` | audit | shared/frontend/requirements.txt | PASS | 8 packages, 0 with known vulnerabilities | `.security-reports/20261021T134310Z-audit-f45a6853.json` |
| `ai-services/mcp-server` | ruff | 15 files | PASS | 0 findings | `.security-reports/20261021T134315Z-ruff-68ab0367.json` |
| `ai-services/mcp-server` | secrets | 18 files | PASS | no new secrets | `.security-reports/20261021T134315Z-secrets-b2139ee2.json` |
| `ai-services/mcp-server` | audit | ai-services/mcp-server/requirements-dev.txt | PASS | 35 packages, 0 with known vulnerabilities | `.security-reports/20261021T134316Z-audit-f7d776b8.json` |
| `ai-services/rag-server` | ruff | 25 files | PASS | 0 findings | `.security-reports/20261021T134321Z-ruff-57c18481.json` |
| `ai-services/rag-server` | secrets | 34 files | PASS | no new secrets | `.security-reports/20261021T134321Z-secrets-57b4813e.json` |
| `ai-services/rag-server` | audit | ai-services/rag-server/requirements-dev.txt | PASS | 16 packages, 0 with known vulnerabilities | `.security-reports/20261021T134321Z-audit-50560ebb.json` |
| `ai-services/multi-agent-server` | ruff | 16 files | PASS | 0 findings | `.security-reports/20261021T134327Z-ruff-ebe59db5.json` |
| `ai-services/multi-agent-server` | secrets | 21 files | PASS | no new secrets | `.security-reports/20261021T134327Z-secrets-ccc15a1f.json` |
| `ai-services/multi-agent-server` | audit | ai-services/multi-agent-server/requirements.txt | PASS | 37 packages, 0 with known vulnerabilities | `.security-reports/20261021T134328Z-audit-3cfa64c5.json` |

## Reproduce

```sh
python3 scripts/security/install.py vgarden   # tools + hook, once
python3 scripts/security/report.py vgarden auth almanac health shared/frontend ai-services/mcp-server ai-services/rag-server ai-services/multi-agent-server --owner "Amy testing evidence refresh" --out docs/evidence/release2/pre-commit-all-services.md
```

## Scope of this refresh

These fresh full scans have `trigger=report`; they do not replace each member's real commit-triggered evidence. See [testing-refresh.md](testing-refresh.md) for source scope and the preserved historical commit evidence.

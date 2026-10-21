# Release 2 contribution log — Guhan Sundar (Plant Health)

Assigned microservices: **Plant Health** (frontend page, backend/API, database) plus the
shared **MCP server** and **RAG server** skeletons from Release 1. GitHub accounts:
`Bageutter` (repository owner), `WTG-Guhan-Sundar`.

Commit history: <https://github.com/Bageutter/Plant-Management-System/commits/main?author=Bageutter>
and <https://github.com/Bageutter/Plant-Management-System/commits/main?author=WTG-Guhan-Sundar>.

## Release 2 work

| Date (2026) | Responsibility (brief) | What was done | Where | Evidence |
| --- | --- | --- | --- | --- |
| 21 Oct | Post-commit CI/CD endpoint testing (criterion 4), issue #73 | `health.yml` tests the two assigned backend functions by name — `routes.create_assessment` (`POST /plant-health-records/assessments`) and `routes.list_assessments` (`GET /plant-health-records/assessments`) — then the rest of the suite as regressions, and keeps JUnit files, logs and `run.json` as a 30-day artifact including on failure; Docker build and compose smoke gated on lint + tests | `.github/workflows/health.yml`, `health/tests/test_endpoints.py`, `.github/README.md` | PR [#77](https://github.com/Bageutter/Plant-Management-System/pull/77); Actions run and artifact linked in the report (§ post-commit testing) |
| 21 Oct | Pre-commit security testing (criterion 3) | Installed the shared tooling for the health service (`scripts/security/install.py health`), ran Ruff security rules, detect-secrets, pip-audit and the health tests on every commit of this release; made `.pre-commit-config.yaml` cross-platform (`language: python`) because the `python3` launcher does not exist on Windows; generated the health report with the shared `scripts/security/report.py` | `.pre-commit-config.yaml` | PR #77; [pre-commit report](pre-commit-guhan.md) |
| 21 Oct | Multi-Agent integration (criteria 1–2) | Plant Health UI → health backend → shared Multi-Agent Server → Planner → Worker → Reviewer → human review on the records page. Evidence sent is only this plant's stored assessments (read through the MCP server's health tools when MCP is on). New `health` source, prompts and `application_integration.submit_task` / `review_task` / terminal CLI on the server; `MULTI_AGENT_HOST` so Linux/WSL containers can reach the server; terminal script through the backend | `health/workflows.py`, `health/templates/_workflow*.html`, `health/integrations.py`, migration `0006`, `ai-services/multi-agent-server/{app,planner,worker,application_integration}.py`, `scripts/test/multi-agent-health.sh` | PR [#79](https://github.com/Bageutter/Plant-Management-System/pull/79); [local run evidence](local-deployment/health-guhan/README.md) |
| 21 Oct | Cloud deployment scripts and workflow (criteria 5–7) | `cloud-deployment.yml` re-runs the CI gates on every push to `main` and deploys to Azure Container Apps through Bicep + reusable scripts under an environment with required reviewers (the human release decision); AI-Mode, MCP, RAG and Multi-Agent disabled by default; deployment report generated per run | `.github/workflows/cloud-deployment.yml`, `infra/*.bicep`, `scripts/deploy/azure-*.sh`, `docs/deployment/azure.md` | PR [#78](https://github.com/Bageutter/Plant-Management-System/pull/78) |
| 21 Oct | Technical report and project evidence (criterion 9) | Release 2 design-flow, Plant Health design-flow, cloud reference architecture and CI/CD pipeline diagrams; local multi-terminal deployment logs; pre-commit report; downloaded post-commit artifact; contribution and commit logs; group report draft and showcase plan | `docs/architecture/`, `docs/evidence/release2/`, `docs/report/` | PR [#82](https://github.com/Bageutter/Plant-Management-System/pull/82) |

Earlier in the release (Release 1, for context): Plant Health CRUD, vision assessment and
the Perceive → Reason → Act → Observe → Repeat loop; the shared MCP and RAG server
skeletons and the health tools/source; Flask-Migrate adoption for auth, vgarden and
health (#60); health UX fixes (#54, #55, #61).

## Responsibilities undertaken

- Owner of the Plant Health microservices end to end (UI, API, schema migrations, tests, CI).
- Kept the Release 1 shared-server integration (MCP, RAG) working while adding the Release 2 Multi-Agent flow, with the same backend-only boundary: the browser never talks to a shared server.
- Repository owner: branch protection, CI workflows, and the Azure deployment pipeline for the group.
- Ran the shared pre-commit checks on every commit of this release and documented the results; fixed the one cross-platform gap found.

## Testing evidence summary

| Check | Result |
| --- | --- |
| `health.yml` endpoint tests (two assigned functions) | run by name on every push/PR; artifact `health-test-evidence-<run>` |
| Health unit/e2e suite | 74 tests passing locally and in CI (fake model, in-process MCP server, fake RAG and Multi-Agent servers) |
| Multi-Agent Server suite | 35 tests (workflow, sources incl. `health`, integration helper, audit) |
| Pre-commit (Ruff S, detect-secrets, pip-audit, health tests) | see the [pre-commit report](pre-commit-guhan.md) |
| Local integrated run | see [local deployment evidence](local-deployment/health-guhan/README.md) |

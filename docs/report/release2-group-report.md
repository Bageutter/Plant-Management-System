# Plant Management System — Release 2 Technical Report (group draft)

> **Status: draft for the group.** Export to `group-<number>.pdf` (max 3000 words).
> Sections marked **[Amy]** / **[Yunus]** / **[group]** need that person's confirmation
> or content; everything else is drawn from the repository as of 21 October 2026.
> Diagrams: `docs/architecture/*.svg`. Evidence: `docs/evidence/release2/`.

| | |
| --- | --- |
| Repository | <https://github.com/Bageutter/Plant-Management-System> |
| Team | Amy Zhou (Plant Almanac), Yunus Sayed (Virtual Garden), Guhan Sundar (Plant Health) |
| Cloud platform | Microsoft Azure (Container Apps, australiaeast) |
| Showcase video | **[group] URL here** (max 10 min) |

## 1. Project overview

The Plant Management System is a microservice web application for small home gardens:
a **Virtual Garden** that is the source of truth for what is planted where, a **Plant
Almanac** of reference knowledge, and **Plant Health** assessments from photos and
descriptions, with shared **auth** and a shared **frontend/proxy**. Every service is
Flask + HTMX + Alpine.js + Jinja (Franken UI) on SQLite in development and PostgreSQL in
the cloud, behind one nginx proxy on `:3000`.

Release 1 added three shared, non-containerised local AI services reached only through
each feature's backend: **AI-Mode** (locally hosted Ollama), the **MCP server** (tools
over each feature's public API) and the **RAG server** (grounded answers with citations
and a confidence category), plus a shared agentic loop with MCP and RAG validation modes.

Release 2 extends that completed application with:

- one shared **Multi-Agent Server** (Planner → Worker → Reviewer → Human Review) that
  all three features call from their frontend UI through their own backend and that is
  also callable from the terminal;
- **local pre-commit security scans** (Ruff security rules, detect-secrets, pip-audit,
  plus the committer's feature tests) that run on every `git commit`;
- **post-commit CI/CD endpoint tests**: each student's workflow tests two endpoint
  functions of their backend after a push and keeps the evidence;
- **cloud deployment** of the integrated application to Azure through
  `cloud-deployment.yml`, Bicep and reusable scripts, with AI-Mode, MCP, RAG and the
  Multi-Agent Server disabled by default;
- the three Release 2 **agentic-loop review modes** (`tools/ai-loop/validate.py --mode
  multi-agent | testing | cloud-deployment`) that review the saved evidence and write a
  review/validation log, alongside the Release 1 `mcp` and `rag` modes.

| Student | Feature microservices | Release 2 responsibilities |
| --- | --- | --- |
| Amy Zhou | Plant Almanac (UI, API, DB) | Multi-Agent Server (Planner/Worker/Reviewer, human review, audit, dashboard); shared pre-commit security tooling; `plant_almanac.yml` endpoint tests |
| Yunus Sayed | Virtual Garden (UI, API, DB); auth, proxy, compose, shared agentic loop | Virtual Garden ↔ Multi-Agent integration with owner-scoped human review; `vgarden.yml` endpoint tests; the Release 2 agentic-loop review modes (`tools/ai-loop/review.py`); Ollama moved out of compose; local-deployment check script |
| Guhan Sundar | Plant Health (UI, API, DB); MCP/RAG server skeletons | Plant Health ↔ Multi-Agent integration; `application_integration` helper; `health.yml` endpoint tests; Azure deployment pipeline; report evidence |

## 2. Final repository structure

```text
.github/workflows/      ruff.yml, integration-ci.yml, plant_almanac.yml (Amy), vgarden.yml (Yunus),
                        health.yml (Guhan), auth.yml, ai-services.yml, cloud-deployment.yml (Azure)
.pre-commit-config.yaml, .secrets.baseline, scripts/security/{install,run_checks,report}.py
auth/ vgarden/ almanac/ health/     feature microservices: app.py, routes, models, migrations/, templates/, tests/
shared/                 templates (nav), frontend, ai_loop.py (shared agentic loop runtime), proxy/
ai-services/mcp-server/           Release 1 shared MCP server (health, almanac, vgarden tools)
ai-services/rag-server/           Release 1 shared RAG server (health, almanac, vgarden sources)
ai-services/multi-agent-server/   Release 2: app.py, planner.py, worker.py, reviewer.py, human_review.py,
                                  application_integration.py, audit.py, store.py, templates/dashboard.html, tests/
tools/ai-loop/          validate.py (mcp, rag + multi-agent, testing, cloud-deployment modes), review.py, logs/ (JSONL + Markdown); tools/ai-dev/
infra/                  main.bicep, apps.bicep, modules/   scripts/deploy/   azure-*.sh (bootstrap → platform → build-push → apps → smoke → report)
scripts/test/           smoke-health.sh, smoke-vgarden.sh, multi-agent-vgarden.sh, multi-agent-health.sh
docs/ai/                AI design (architecture, context, prompts, agentic loop, MCP/RAG design)
docs/architecture/      Release 2 design flow, Plant Health flow, cloud architecture, CI/CD pipeline (.mmd/.svg/.png)
docs/deployment/azure.md          cloud walkthrough
docs/evidence/release2/           design-flow.md, multi-agent evidence (vgarden + health), pre-commit-*.md, post-commit/,
                                  testing/, testing-review.md, multi-agent-review.md, local-deployment/ (+ health-guhan/),
                                  cloud-deployment/, contribution-*.md, github-commit-log.md
docs/report/            this report, showcase plan
docker-compose.yml      proxy, frontend, auth, vgarden, almanac, health, ollama (AI services are NOT compose services)
```

## 3. Release 2 design flow

![Release 2 design flow](../architecture/release2-design-flow.svg)

(Mermaid sources: `docs/architecture/release2-design-flow.mmd`; Yunus's per-flow
diagrams: `docs/evidence/release2/design-flow.md`.)

**Frontend UI → Backend/API → Database.** Each page talks only to its own Flask backend
(HTMX fragments or JSON); each backend owns its database and schema migrations
(Flask-Migrate/Alembic, applied at start-up).

**Release 1 flows (retained).** *AI-Mode*: Plant Health runs its vision assessment inside
a Perceive → Reason → Act → Observe → Repeat loop (code checks + an independent reviewer
model); the Almanac and Virtual Garden chats run Plan → Act → Observe → Adapt. *MCP*: each
backend exposes a whitelisted `tools/run` route that calls the shared MCP server, which
in turn reads only the features' public APIs. *RAG*: each backend's `ask` route queries
the shared RAG server, which indexes records through the same APIs and answers with
citations and a confidence category.

**Release 2 flow.** Frontend UI → Backend/API → `POST /workflow` on the Multi-Agent
Server → **Planner** (plans information-processing steps) → **Worker** (answers only
from the supplied evidence, citing passage ids) → **Reviewer** (checks the answer against
the same evidence, recommends accept/revise) → **Human Review** on the feature's own page
(accept, partially accept, request changes, reject; requested changes trigger a revised
run with the feedback) → response shown in the frontend UI. Evidence boundaries differ by
feature: the Almanac Worker retrieves public references through MCP; Virtual Garden sends
one garden's snapshot and Plant Health sends one plant's stored assessments, so the server
never reads private or feature-owned data itself.

### Plant Health design flow (Guhan)

![Plant Health design flow](../architecture/plant-health-design-flow.svg)

The records page has four entry points, all routed through `health/routes.py` and
`health/workflows.py`: the assessment form (AI-Mode + agentic loop), the MCP tools
panel, the RAG panel, and the new *Agent workflow* panel. The workflow panel sends the
task plus a history-summary passage and up to eight of the plant's assessments (read
through the MCP server's `list_health_assessments`/`get_health_assessment` tools when MCP
is on, otherwise from the database), polls the backend every 3 s while the three agents
run, and records the gardener's decision. **[Amy]** and **[Yunus]**: one paragraph each on
your feature's updated flow (see `docs/evidence/release2/multi-agent-vgarden.md`).

## 4. Cloud deployment and CI/CD architecture

![Cloud reference architecture](../architecture/cloud-architecture.svg)

The cloud layout mirrors `docker-compose.yml`: the same six images in one **Azure
Container Apps** environment inside a VNet, the nginx **proxy** as the only public HTTPS
ingress, the five services on internal ingress, one **PostgreSQL Flexible Server**
(private subnet, one database per service), **Key Vault** for secrets read through a
managed identity, **Container Registry** (images tagged with the commit SHA), **Azure
Files** for Almanac images and **Log Analytics**. GitHub Actions signs in with OIDC, so
no cloud credential is stored in GitHub. The cloud baseline keeps AI-Mode, MCP, RAG and
the Multi-Agent Server **disabled** (`MCP_ENABLED=false`, `RAG_ENABLED=false`,
`MULTI_AGENT_ENABLED=false`, unreachable `OLLAMA_URL`); the smoke step asserts the
`/integrations` endpoints report exactly that.

![CI/CD pipeline](../architecture/cicd-pipeline.svg)

**DevOps flow.** Source control (feature branch) → local pre-commit scans on `git commit`
→ push / pull request → GitHub Actions: `ruff.yml`, `integration-ci.yml` and the three
student workflows run the two assigned endpoint functions per student (JUnit + logs kept
as artifacts) → Docker build and compose smoke validation → merge to `main` →
`cloud-deployment.yml` re-runs the gates (lint, endpoint tests ×4 services, build +
smoke) → the `azure-production` environment's required reviewers give the human release
decision → `azure-platform.sh` (Bicep) → `azure-build-push.sh` → `azure-apps.sh` →
`azure-smoke.sh` → `azure-report.sh` writes the deployment report into
`docs/evidence/release2/cloud-deployment/`.

## 5. Pre-commit security testing

`.pre-commit-config.yaml` installs four local hooks (`scripts/security/install.py
<service>`), each a stdlib launcher that runs the tool from an isolated virtual
environment and stores JSON evidence under `.security-reports/`:

| Hook | Tool | Scope |
| --- | --- | --- |
| `ruff-security` | Ruff `--select S` (Bandit-derived rules) | staged Python files |
| `detect-secrets` | `detect-secrets-hook --baseline .secrets.baseline` | staged files |
| `pip-audit` | `pip-audit -r <service>/requirements-dev.txt` | services with staged changes |
| `pytest` | the committer's feature tests with AI services disabled | `<service>/tests` |

A failing hook blocks the commit; findings are fixed or carry a reviewed `# noqa` with a
reason. During Release 2 the hooks were made cross-platform (`language: python`) after
the `python3` launcher failed on Windows. Per-student reports (generated by
`scripts/security/report.py`, raw output never shared):

| Student | Latest result | Report |
| --- | --- | --- |
| Guhan Sundar (health) | full scan of the health service + the hook runs on this release's commits — see the page for counts | `docs/evidence/release2/pre-commit-guhan.md` |
| Yunus Sayed (vgarden, auth) | all four checks PASS for both services (10 Ruff security findings fixed first); 137 + 10 tests | `docs/evidence/release2/pre-commit-yunus.md` |
| Amy Zhou (almanac) | **[Amy]** generate with `scripts/security/report.py almanac --owner "Amy Zhou" --out docs/evidence/release2/pre-commit-amy.md` | `docs/evidence/release2/pre-commit-amy.md` |
| All services | one page scanning every service, for the Testing review | `docs/evidence/release2/pre-commit-all-services.md` |

## 6. Post-commit CI/CD endpoint testing

Each student's workflow runs the two assigned backend functions by name after every
push, then the rest of the suite as regressions, and uploads `endpoints.xml`,
`endpoints.log`, `regressions.xml`, `regressions.log` and `run.json` (source SHA, run
URL, function names) as a 30-day artifact — including when a test fails. Docker builds
depend on lint and tests passing. Tests use temporary SQLite and fakes for the model and
shared servers, so no AI service runs in CI.

| Student · workflow | Backend function | Route | Test |
| --- | --- | --- | --- |
| Amy · `plant_almanac.yml` | `catalogue_api.search` | `GET /api/catalogue` | `test_public_catalogue_search_pages_and_literal_search` |
| | `catalogue_api.plant` | `GET /api/catalogue/plant/<slug>` | `test_public_details_preserve_evidence_and_make_no_writes` |
| Yunus · `vgarden.yml` | `routes.create_garden` | `POST /gardens` | `test_create_garden_validates_input_and_persists` |
| | `routes.garden_snapshot` | `GET /gardens/<id>/snapshot` | `test_garden_snapshot_returns_scoped_evidence_and_makes_no_writes` |
| Guhan · `health.yml` | `routes.create_assessment` | `POST /plant-health-records/assessments` | `test_create_assessment_validates_input_and_persists` |
| | `routes.list_assessments` | `GET /plant-health-records/assessments` | `test_list_assessments_filters_pages_and_makes_no_writes` |

### 6.3 Plant Health (Guhan)

`test_create_assessment_validates_input_and_persists` covers every validation path
(empty body, over-long fields, wrong types, bad or unsupported images) and the 503 when
the local model is down — all writing nothing — then the 201 response, persistence of
the record, its agentic-loop run and the plant title, history passed on a repeat
assessment, a photo stored and served back, and the HTMX fragment.
`test_list_assessments_filters_pages_and_makes_no_writes` covers the empty list,
newest-first order, the `plant_ref`/`status`/`since` filters and their 400s,
`limit`/`offset` clamping, that image bytes never travel in the listing, and that
repeated reads change nothing.

| Evidence | Value |
| --- | --- |
| Commit | `c11bc73e82` on `claude/plant-health-release-2-tests-1b9e16` (PR #77; replace with the merge commit on `main` once merged) |
| Successful push run | <https://github.com/Bageutter/Plant-Management-System/actions/runs/39560544593> (`Plant Health (Guhan)`, event `push`, all jobs green: Lint, Tests, Docker image builds, Compose smoke test) |
| Result | endpoints: 2 passed, 0 failed · regressions: 60 passed, 0 failed (see the downloaded JUnit files) |
| Artifact | `health-test-evidence-39560544593-1` — downloaded to `docs/evidence/release2/post-commit/health-guhan/` (`endpoints.xml`, `endpoints.log`, `regressions.xml`, `regressions.log`, `run.json`) |

### 6.1 Plant Almanac (Amy) · 6.2 Virtual Garden (Yunus)

Latest successful **push** runs on `main` at the time of writing (confirm, and add the
pass/fail counts and artifact names from the run's `endpoints.xml` / `regressions.xml`):

| Workflow | Commit on `main` | Push run |
| --- | --- | --- |
| `plant_almanac.yml` (Amy) | `0d330db067` | <https://github.com/Bageutter/Plant-Management-System/actions/runs/39428279251> |
| `vgarden.yml` (Yunus) | `0a31150520` | <https://github.com/Bageutter/Plant-Management-System/actions/runs/39495422400> |

**[Amy]** and **[Yunus]**: one paragraph each on what your two tests check (the
`.github/README.md` sections already describe them).

## 7. Testing review (agentic loop)

`tools/ai-loop/validate.py --mode testing` reviews the pre-commit pages (§5) and every
service's test run with endpoint coverage (`docs/evidence/release2/testing/`) through the
Plan → Act → Observe → Adapt loop with a reviewer model, and writes
`docs/evidence/release2/testing-review.md` + `review-testing.json` plus the validation
log `tools/ai-loop/logs/review-testing.jsonl`. The run on `main` at the time of writing
(`review-testing-20261021-104049-dfe5eb`) returned **not_ready** — 35 of 54 checks
passing, the failures being services whose evidence was not yet merged — with the human
decision pending. **[group]** Re-run after PRs #82 and #84 merge and paste the final
verdict, check counts and human decision here.

## 8. Local deployment evidence

Two independent local runs, both in `docs/evidence/release2/local-deployment/`:
Yunus's on macOS (`check.txt`: 31 of 31 checks — containers up, no AI service in
compose, each host service healthy, every backend reachable through the proxy and
reaching the host services from inside its container) and Guhan's on Windows/WSL
(`health-guhan/`), summarised here. The integrated application ran with the containers
under Docker Compose and the AI services as separate host processes, each in its own
terminal:

| Terminal | Process | Log (`local-deployment/health-guhan/`) |
| --- | --- | --- |
| 1 | `docker compose up -d --build` (proxy, frontend, auth, vgarden, almanac, health; the `ollama` container that compose still had at the time) | `terminal-1-compose-up.log` |
| 2 | `MCP_HOST=0.0.0.0 python ai-services/mcp-server/server.py` | `terminal-2-mcp-server.log` |
| 3 | `RAG_HOST=0.0.0.0 python ai-services/rag-server/app.py` | `terminal-3-rag-server.log` |
| 4 | `MULTI_AGENT_HOST=0.0.0.0 python ai-services/multi-agent-server/app.py` | `terminal-4-multi-agent-server.log` |
| 5 | Plant Health through the proxy: CRUD, AI-Mode assessments, MCP tool, RAG answer | `terminal-5-health-walkthrough.log` |
| 6 | `bash scripts/test/multi-agent-health.sh` — Planner → Worker → Reviewer → human review through the health backend | `terminal-6-multi-agent-health.log` |

Outcome (21 Oct 2026, one laptop, CPU-only Ollama): all seven containers and the three
host servers ran together; `/health/plant-health-records/integrations` and
`/vgarden/integrations` reported MCP, RAG and Multi-Agent enabled and reachable; four
assessments ran through the vision model and reviewer loop (23–126 s each); the MCP
history tool answered in 127 ms and the RAG question in 28 s with two citations at
medium confidence; the multi-agent workflow completed Planner → Worker → Reviewer →
request changes → revised run → Reviewer → partial acceptance in 3 min 22 s from the
terminal, and a second workflow was started and accepted from the records page. Full
write-up and logs: `docs/evidence/release2/local-deployment/health-guhan/README.md`.

## 9. Cloud deployment report and review

**[Guhan, after the first workflow run]** The deployment pipeline (PR #78) is
implemented; the first run creates the resources (15–20 min) and
`scripts/deploy/azure-report.sh` writes `docs/evidence/release2/cloud-deployment/
cloud-deployment-<timestamp>.md` with the resource names, image tags, the proxy URL, the
`/integrations` baseline check and the smoke results. Include here: that report, a
screenshot of the deployed frontend UI with a CRUD action, the `cloud-deployment.yml`
run URL with the environment approval (the final human release decision), and
**[group]** the agentic loop's *Cloud Deployment Report Review* output and log.

## 10. Multi-Agent workflow evidence

Server-side evidence for every workflow: `GET /workflow/status` (plan, evidence, answer,
review, human decision, full history) and the audit exports
`workflow_history.jsonl` (every event) and `coordination_audit.jsonl` (hand-offs, model
per role, decisions), also downloadable from `/dashboard`.

| Feature | Evidence | What it shows |
| --- | --- | --- |
| Virtual Garden (Yunus) | `docs/evidence/release2/multi-agent-vgarden.md`, `multi-agent-terminal-run.txt`, `workflow_history.jsonl`, `coordination_audit.jsonl`, `multi-agent-metrics.json` | Six workflows through the UI and the terminal; a Worker bug found and fixed from the audit; human decisions including request-changes and partial acceptance |
| Plant Health (Guhan) | `docs/evidence/release2/local-deployment/health-guhan/` (terminal 6 transcript, UI run write-up, `workflow_history.jsonl`, `coordination_audit.jsonl`, `multi-agent-metrics.json`, `health-workflows.json`) | Terminal: workflow `a7f23d6d` through the health backend with evidence read via MCP — two agent runs, a human request for changes that reached both the Planner and the Worker, a Reviewer `revise` on each run, partial acceptance. UI: workflow `ae71c81a` started and accepted (with the required reason) from the records page. The first attempt exposed and fixed a Reviewer failure mode (mangled quote → failed stage) |
| Plant Almanac (Amy) | **[Amy]** | |
| Agentic-loop *Multi-Agent review* | `docs/evidence/release2/multi-agent-review.md`, `review-multi-agent.json`, `tools/ai-loop/logs/review-multi-agent.jsonl` | Run `review-multi-agent-20261021-112329-f18b5a`: verdict **ready** — every run went Planner → Worker → Reviewer → human review in order, every workflow closed by a human, citations grounded; human decision **[group]** to record |

## 11. GitHub commit logs

<https://github.com/Bageutter/Plant-Management-System/commits/main> — each student's
Release 2 commits and pull requests are listed in
`docs/evidence/release2/github-commit-log.md` (per-author filters:
`?author=0melette`, `?author=yunz-dev`, `?author=Bageutter`).

## 12. Contribution logs

| Student | Log |
| --- | --- |
| Guhan Sundar | `docs/evidence/release2/contribution-guhan.md` |
| Yunus Sayed | `docs/evidence/release2/contribution-yunus.md` |
| Amy Zhou | **[Amy]** `docs/evidence/release2/contribution-amy.md` |

## 13. Bonus evidence

No bonus marks are claimed in this draft. (The Azure pipeline has a bonus profile that
would enable the AI services; it is not deployed.)

## 14. Showcase video URL

**[group]** Published URL (max 10 minutes, all students). Plan and shot list:
`docs/report/showcase-video-plan.md`.

# Testing review

Run `review-testing-20261021-104049-dfe5eb` · verdict **not_ready** (from checks after capped model) · human decision **pending** by `yunus`

35 of 54 checks passed. Not passing: TS-9 (fail), TS-13 (fail), TS-16 (fail), TS-17 (fail), TS-20 (fail), TS-23 (fail), TS-25 (fail), TS-31 (missing), TS-35 (fail), TS-40 (warn), TS-42 (warn), TS-44 (warn), TS-45 (fail), TS-46 (warn), TS-47 (warn), TS-48 (warn), TS-50 (warn), TS-52 (warn), TS-54 (warn).

## Checks

| ID | Check | Result | Detail |
| --- | --- | --- | --- |
| TS-1 | Pre-commit ruff check passes for vgarden | ✅ pass | 0 Ruff security findings (2026-10-21T10:39, trigger report). |
| TS-2 | Pre-commit secrets check passes for vgarden | ✅ pass | no new secrets (2026-10-21T10:39, trigger report). |
| TS-3 | Pre-commit audit check passes for vgarden | ✅ pass | 53 packages, 0 with known vulnerabilities (2026-10-21T10:39, trigger report). |
| TS-4 | Pre-commit tests check passes for vgarden | ✅ pass | 137 passed in 10.82s (2026-10-21T10:39, trigger report). |
| TS-5 | Pre-commit ruff check passes for auth | ✅ pass | 0 Ruff security findings (2026-10-21T10:40, trigger report). |
| TS-6 | Pre-commit secrets check passes for auth | ✅ pass | no new secrets (2026-10-21T10:40, trigger report). |
| TS-7 | Pre-commit audit check passes for auth | ✅ pass | 29 packages, 0 with known vulnerabilities (2026-10-21T10:40, trigger report). |
| TS-8 | Pre-commit tests check passes for auth | ✅ pass | 10 passed in 1.28s (2026-10-21T10:40, trigger report). |
| TS-9 | Pre-commit ruff check passes for almanac | ❌ fail | 10 Ruff security findings (2026-10-21T10:40, trigger report). |
| TS-10 | Pre-commit secrets check passes for almanac | ✅ pass | no new secrets (2026-10-21T10:40, trigger report). |
| TS-11 | Pre-commit audit check passes for almanac | ✅ pass | 47 packages, 0 with known vulnerabilities (2026-10-21T10:40, trigger report). |
| TS-12 | Pre-commit tests check passes for almanac | ✅ pass | 74 passed in 5.73s (2026-10-21T10:40, trigger report). |
| TS-13 | Pre-commit ruff check passes for health | ❌ fail | 4 Ruff security findings (2026-10-21T10:40, trigger report). |
| TS-14 | Pre-commit secrets check passes for health | ✅ pass | no new secrets (2026-10-21T10:40, trigger report). |
| TS-15 | Pre-commit audit check passes for health | ✅ pass | 52 packages, 0 with known vulnerabilities (2026-10-21T10:40, trigger report). |
| TS-16 | Pre-commit tests check passes for health | ❌ fail | 60 errors in 1.11s (2026-10-21T10:40, trigger report). |
| TS-17 | Pre-commit ruff check passes for shared/frontend | ❌ fail | 2 Ruff security findings (2026-10-21T10:40, trigger report). |
| TS-18 | Pre-commit secrets check passes for shared/frontend | ✅ pass | no new secrets (2026-10-21T10:40, trigger report). |
| TS-19 | Pre-commit audit check passes for shared/frontend | ✅ pass | 7 packages, 0 with known vulnerabilities (2026-10-21T10:40, trigger report). |
| TS-20 | Pre-commit ruff check passes for ai-services/mcp-server | ❌ fail | 5 Ruff security findings (2026-10-21T10:40, trigger report). |
| TS-21 | Pre-commit secrets check passes for ai-services/mcp-server | ✅ pass | no new secrets (2026-10-21T10:40, trigger report). |
| TS-22 | Pre-commit audit check passes for ai-services/mcp-server | ✅ pass | 35 packages, 0 with known vulnerabilities (2026-10-21T10:40, trigger report). |
| TS-23 | Pre-commit ruff check passes for ai-services/rag-server | ❌ fail | 5 Ruff security findings (2026-10-21T10:40, trigger report). |
| TS-24 | Pre-commit secrets check passes for ai-services/rag-server | ✅ pass | no new secrets (2026-10-21T10:40, trigger report). |
| TS-25 | Pre-commit audit check passes for ai-services/rag-server | ❌ fail | 92 packages, 1 with known vulnerabilities (2026-10-21T10:40, trigger report). |
| TS-26 | Pre-commit ruff check passes for ai-services/multi-agent-server | ✅ pass | 0 Ruff security findings (2026-10-21T10:40, trigger report). |
| TS-27 | Pre-commit secrets check passes for ai-services/multi-agent-server | ✅ pass | no new secrets (2026-10-21T10:40, trigger report). |
| TS-28 | Pre-commit audit check passes for ai-services/multi-agent-server | ✅ pass | 37 packages, 0 with known vulnerabilities (2026-10-21T10:40, trigger report). |
| TS-29 | Latest vgarden.yml run on main succeeded | ✅ pass | run 39495422400 on 0a31150 (push): success; jobs: Lint=success, Tests=success, Docker image builds=success, Compose smoke test (MCP + RAG + Multi-Agent disabled)=success |
| TS-30 | vgarden.yml ran the assigned endpoint tests | ✅ pass | 'Test the two assigned endpoint functions'=success; 'Save endpoint and regression test evidence'=success |
| TS-31 | Latest auth.yml run on main succeeded | ❔ missing | No finished auth.yml run on main. |
| TS-32 | Latest plant_almanac.yml run on main succeeded | ✅ pass | run 39428279251 on 0d330db (push): success; jobs: Tests=success, Lint=success, Docker image builds=success |
| TS-33 | plant_almanac.yml ran the assigned endpoint tests | ✅ pass | 'Test the two assigned endpoint functions'=success; 'Save endpoint and regression test evidence'=success |
| TS-34 | Latest health.yml run on main succeeded | ✅ pass | run 39495422359 on 0a31150 (push): success; jobs: Docker image builds=success, Lint=success, Unit + e2e tests=success, Compose smoke test (MCP + RAG disabled)=success |
| TS-35 | health.yml ran the assigned endpoint tests | ❌ fail | No endpoint test step found. |
| TS-36 | Latest ai-services.yml run on main succeeded | ✅ pass | run 39495422562 on 0a31150 (push): success; jobs: MCP server tests=success, Lint=success, RAG server tests=success |
| TS-37 | Latest integration-ci.yml run on main succeeded | ✅ pass | run 39495422420 on 0a31150 (push): success; jobs: Validate and build Compose stack=success, Start stack and smoke-check services=success |
| TS-38 | Latest ruff.yml run on main succeeded | ✅ pass | run 39495422419 on 0a31150 (push): success; jobs: Python lint=success |
| TS-39 | vgarden tests pass | ✅ pass | 137 tests: 0 failures, 0 errors, 0 skipped (commit 48fcee1). |
| TS-40 | Every vgarden endpoint is exercised by a test | ⚠️ warn | 34/36 endpoints run by the tests; not exercised: GET /healthz, GET /gardens Line coverage 95.5%. |
| TS-41 | auth tests pass | ✅ pass | 10 tests: 0 failures, 0 errors, 0 skipped (commit 48fcee1). |
| TS-42 | Every auth endpoint is exercised by a test | ⚠️ warn | 2/8 endpoints run by the tests; not exercised: GET/POST /register, POST /logout, GET /account, POST /gardens, POST /gardens/<int:garden_id>/delete, GET /me Line coverage 77.3%. |
| TS-43 | almanac tests pass | ✅ pass | 74 tests: 0 failures, 0 errors, 0 skipped (commit 48fcee1). |
| TS-44 | Every almanac endpoint is exercised by a test | ⚠️ warn | 28/29 endpoints run by the tests; not exercised: GET /health Line coverage 91.6%. |
| TS-45 | health tests pass | ❌ fail | 60 tests: 0 failures, 60 errors, 0 skipped (commit 48fcee1). |
| TS-46 | Every health endpoint is exercised by a test | ⚠️ warn | 0/23 endpoints run by the tests; not exercised: GET /, GET /healthz, GET /, GET /<int:assessment_id>, GET /<int:assessment_id>/image, POST /assessments, POST /assessments/stream, GET /assessments and 15 more Line coverage 19.8%. |
| TS-47 | shared/frontend tests pass | ⚠️ warn | The service has no tests. |
| TS-48 | Every shared/frontend endpoint is exercised by a test | ⚠️ warn | 0/1 endpoints run by the tests; not exercised: GET / Line coverage None%. |
| TS-49 | ai-services/mcp-server tests pass | ✅ pass | 42 tests: 0 failures, 0 errors, 0 skipped (commit 48fcee1). |
| TS-50 | Every ai-services/mcp-server endpoint is exercised by a test | ⚠️ warn | 12/13 endpoints run by the tests; not exercised: GET /healthz Line coverage 95.0%. |
| TS-51 | ai-services/rag-server tests pass | ✅ pass | 68 tests: 0 failures, 0 errors, 0 skipped (commit 48fcee1). |
| TS-52 | Every ai-services/rag-server endpoint is exercised by a test | ⚠️ warn | 5/6 endpoints run by the tests; not exercised: POST /rag/retrieve Line coverage 89.2%. |
| TS-53 | ai-services/multi-agent-server tests pass | ✅ pass | 25 tests: 0 failures, 0 errors, 0 skipped (commit 48fcee1). |
| TS-54 | Every ai-services/multi-agent-server endpoint is exercised by a test | ⚠️ warn | 5/8 endpoints run by the tests; not exercised: GET /healthz, GET /dashboard, GET /workflow/metrics Line coverage 88.7%. |

## Tests and endpoint coverage per service

| Service | Tests | Failures + errors | Skipped | Warnings | Line coverage | Endpoints exercised |
| --- | --- | --- | --- | --- | --- | --- |
| `vgarden` | 137 | 0 | 0 | 0 | 95.5% | 34/36 |
| `auth` | 10 | 0 | 0 | 0 | 77.3% | 2/8 |
| `almanac` | 74 | 0 | 0 | 0 | 91.6% | 28/29 |
| `health` | 60 | 60 | 0 | 0 | 19.8% | 0/23 |
| `shared/frontend` | 0 | 0 | 0 | 0 | None% | 0/1 |
| `ai-services/mcp-server` | 42 | 0 | 0 | 0 | 95.0% | 12/13 |
| `ai-services/rag-server` | 68 | 0 | 0 | 0 | 89.2% | 5/6 |
| `ai-services/multi-agent-server` | 25 | 0 | 0 | 0 | 88.7% | 5/8 |

### Endpoints no test exercises

- **`vgarden`**: `GET /healthz (vgarden/routes.py:93)`, `GET /gardens (vgarden/routes.py:212)`
- **`auth`**: `GET/POST /register (auth/routes.py:32)`, `POST /logout (auth/routes.py:72)`, `GET /account (auth/routes.py:79)`, `POST /gardens (auth/routes.py:114)`, `POST /gardens/<int:garden_id>/delete (auth/routes.py:149)`, `GET /me (auth/routes.py:211)`
- **`almanac`**: `GET /health (almanac/app.py:923)`
- **`health`**: `GET / (health/routes.py:72)`, `GET /healthz (health/routes.py:77)`, `GET / (health/routes.py:96)`, `GET /<int:assessment_id> (health/routes.py:101)`, `GET /<int:assessment_id>/image (health/routes.py:114)`, `POST /assessments (health/routes.py:137)`, `POST /assessments/stream (health/routes.py:159)`, `GET /assessments (health/routes.py:263)`, `GET /assessments/<int:assessment_id> (health/routes.py:305)`, `PATCH/PUT /assessments/<int:assessment_id> (health/routes.py:313)`, `DELETE /assessments/<int:assessment_id> (health/routes.py:343)`, `POST /assessments/<int:assessment_id>/regenerate (health/routes.py:358)`, `POST /assessments/<int:assessment_id>/regenerate/stream (health/routes.py:389)`, `GET /assessments/<int:assessment_id>/loop (health/routes.py:403)`, `GET /<int:assessment_id>/loop (health/routes.py:413)`, `GET /plants (health/routes.py:573)`, `POST /plants (health/routes.py:583)`, `DELETE /plants/<int:plant_id> (health/routes.py:605)`, `GET /integrations (health/routes.py:651)`, `GET /tools (health/routes.py:674)`, `POST /tools/run (health/routes.py:684)`, `POST /ask (health/routes.py:708)`, `POST /ask/sync (health/routes.py:727)`
- **`shared/frontend`**: `GET / (shared/frontend/app.py:21)`
- **`ai-services/mcp-server`**: `GET /healthz (ai-services/mcp-server/server.py:60)`
- **`ai-services/rag-server`**: `POST /rag/retrieve (ai-services/rag-server/routes.py:213)`
- **`ai-services/multi-agent-server`**: `GET /healthz (ai-services/multi-agent-server/app.py:18)`, `GET /dashboard (ai-services/multi-agent-server/app.py:130)`, `GET /workflow/metrics (ai-services/multi-agent-server/app.py:147)`

## Findings

- **TS-9** (major): Pre-commit ruff check passes for almanac: 10 Ruff security findings (2026-10-21T10:40, trigger report).
- **TS-13** (major): Pre-commit ruff check passes for health: 4 Ruff security findings (2026-10-21T10:40, trigger report).
- **TS-16** (major): Pre-commit tests check passes for health: 60 errors in 1.11s (2026-10-21T10:40, trigger report).
- **TS-17** (major): Pre-commit ruff check passes for shared/frontend: 2 Ruff security findings (2026-10-21T10:40, trigger report).
- **TS-20** (major): Pre-commit ruff check passes for ai-services/mcp-server: 5 Ruff security findings (2026-10-21T10:40, trigger report).
- **TS-23** (major): Pre-commit ruff check passes for ai-services/rag-server: 5 Ruff security findings (2026-10-21T10:40, trigger report).
- **TS-25** (major): Pre-commit audit check passes for ai-services/rag-server: 92 packages, 1 with known vulnerabilities (2026-10-21T10:40, trigger report).
- **TS-31** (blocker): Latest auth.yml run on main succeeded: No finished auth.yml run on main.
- **TS-35** (major): health.yml ran the assigned endpoint tests: No endpoint test step found.
- **TS-40** (minor): Every vgarden endpoint is exercised by a test: 34/36 endpoints run by the tests; not exercised: GET /healthz, GET /gardens Line coverage 95.5%.
- **TS-42** (minor): Every auth endpoint is exercised by a test: 2/8 endpoints run by the tests; not exercised: GET/POST /register, POST /logout, GET /account, POST /gardens, POST /gardens/<int:garden_id>/delete, GET /me Line coverage 77.3%.
- **TS-44** (minor): Every almanac endpoint is exercised by a test: 28/29 endpoints run by the tests; not exercised: GET /health Line coverage 91.6%.
- **TS-45** (major): health tests pass: 60 tests: 0 failures, 60 errors, 0 skipped (commit 48fcee1).
- **TS-46** (minor): Every health endpoint is exercised by a test: 0/23 endpoints run by the tests; not exercised: GET /, GET /healthz, GET /, GET /<int:assessment_id>, GET /<int:assessment_id>/image, POST /assessments, POST /assessments/stream, GET /assessments and 15 more Line coverage 19.8%.
- **TS-47** (minor): shared/frontend tests pass: The service has no tests.
- **TS-48** (minor): Every shared/frontend endpoint is exercised by a test: 0/1 endpoints run by the tests; not exercised: GET / Line coverage None%.
- **TS-50** (minor): Every ai-services/mcp-server endpoint is exercised by a test: 12/13 endpoints run by the tests; not exercised: GET /healthz Line coverage 95.0%.
- **TS-52** (minor): Every ai-services/rag-server endpoint is exercised by a test: 5/6 endpoints run by the tests; not exercised: POST /rag/retrieve Line coverage 89.2%.
- **TS-54** (minor): Every ai-services/multi-agent-server endpoint is exercised by a test: 5/8 endpoints run by the tests; not exercised: GET /healthz, GET /dashboard, GET /workflow/metrics Line coverage 88.7%.

## Recommendations

- Resolve TS-9: pre-commit ruff check passes for almanac.
- Resolve TS-13: pre-commit ruff check passes for health.
- Resolve TS-16: pre-commit tests check passes for health.
- Resolve TS-17: pre-commit ruff check passes for shared/frontend.
- Resolve TS-20: pre-commit ruff check passes for ai-services/mcp-server.
- Resolve TS-23: pre-commit ruff check passes for ai-services/rag-server.
- Resolve TS-25: pre-commit audit check passes for ai-services/rag-server.
- Resolve TS-31: latest auth.yml run on main succeeded.
- Resolve TS-35: health.yml ran the assigned endpoint tests.
- Resolve TS-40: every vgarden endpoint is exercised by a test.
- Resolve TS-42: every auth endpoint is exercised by a test.
- Resolve TS-44: every almanac endpoint is exercised by a test.
- Resolve TS-45: health tests pass.
- Resolve TS-46: every health endpoint is exercised by a test.
- Resolve TS-47: shared/frontend tests pass.
- Resolve TS-48: every shared/frontend endpoint is exercised by a test.
- Resolve TS-50: every ai-services/mcp-server endpoint is exercised by a test.
- Resolve TS-52: every ai-services/rag-server endpoint is exercised by a test.
- Resolve TS-54: every ai-services/multi-agent-server endpoint is exercised by a test.

## Human decision

- Decision: **pending** (choices: accept, partially_accept, reject)
- Reason: No --decision given and no terminal to ask.

## Evidence and log

- .security-reports/20261021T103944Z-ruff-e97e526c.json
- .security-reports/20261021T103944Z-secrets-0c6bea2b.json
- .security-reports/20261021T103945Z-audit-bebc0d8d.json
- .security-reports/20261021T103950Z-tests-7b5bcd84.json
- .security-reports/20261021T104002Z-ruff-955c45df.json
- .security-reports/20261021T104002Z-secrets-1ff1faa3.json
- .security-reports/20261021T104002Z-audit-4093b8ad.json
- .security-reports/20261021T104006Z-tests-1ac6e6aa.json
- .security-reports/20261021T104008Z-ruff-6a401bf7.json
- .security-reports/20261021T104008Z-secrets-ed7d0b40.json
- .security-reports/20261021T104009Z-audit-ad64f2c0.json
- .security-reports/20261021T104014Z-tests-a64a2279.json
- .security-reports/20261021T104020Z-ruff-29615c69.json
- .security-reports/20261021T104020Z-secrets-6655c542.json
- .security-reports/20261021T104021Z-audit-dfd86282.json
- .security-reports/20261021T104026Z-tests-4ef2df68.json
- .security-reports/20261021T104028Z-ruff-1c75d824.json
- .security-reports/20261021T104028Z-secrets-89580e08.json
- .security-reports/20261021T104028Z-audit-cdabd089.json
- .security-reports/20261021T104032Z-ruff-6b1b3c3d.json
- .security-reports/20261021T104032Z-secrets-177dc3d7.json
- .security-reports/20261021T104032Z-audit-5c48b76d.json
- .security-reports/20261021T104037Z-ruff-18955f4a.json
- .security-reports/20261021T104037Z-secrets-bad3dd86.json
- .security-reports/20261021T104038Z-audit-b92c4676.json
- .security-reports/20261021T104044Z-ruff-f6533d02.json
- .security-reports/20261021T104044Z-secrets-6cb69c77.json
- .security-reports/20261021T104045Z-audit-c6262b95.json
- https://github.com/Bageutter/Plant-Management-System/actions/runs/39495422400
- https://github.com/Bageutter/Plant-Management-System/actions/runs/39428279251
- https://github.com/Bageutter/Plant-Management-System/actions/runs/39495422359
- https://github.com/Bageutter/Plant-Management-System/actions/runs/39495422562
- https://github.com/Bageutter/Plant-Management-System/actions/runs/39495422420
- https://github.com/Bageutter/Plant-Management-System/actions/runs/39495422419
- docs/evidence/release2/testing/vgarden
- docs/evidence/release2/testing/auth
- docs/evidence/release2/testing/almanac
- docs/evidence/release2/testing/health
- docs/evidence/release2/testing/frontend
- docs/evidence/release2/testing/mcp-server
- docs/evidence/release2/testing/rag-server
- docs/evidence/release2/testing/multi-agent-server
- Review/validation log: `tools/ai-loop/logs/reports/review-testing/review-testing-20261021-104049-dfe5eb.md`

_Reviews saved evidence; a passing review is not proof that every feature works._

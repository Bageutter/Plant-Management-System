# github stuff

## workflows

| file | what it does |
| --- | --- |
| `ruff.yml` | python lint gate — runs on **every PR and push** to `main` |
| `integration-ci.yml` | integration CI — builds, smoke-checks, and tears down the stack |
| `plant_almanac.yml` | Amy's Almanac CI — Ruff, compile check, two named endpoint tests, remaining pytest suite, retained test evidence, and Docker build; runs for matching `main`/`amy/**` pushes, PRs and manual runs |
| `vgarden.yml` | Yunus's Virtual Garden CI — Ruff, compile check, two named endpoint tests, remaining pytest suite, retained test evidence, Docker build and compose smoke test; runs for matching `main`/`yunz/**` pushes, PRs and manual runs |
| `health.yml` | health monitoring service CI — triggers on `bageutter/**` branches and `health/` path changes |
| `cloud-deployment.yml` | **Release 2 cloud deployment** — re-runs the gates (Ruff, every service's endpoint tests, Docker build + compose smoke) and, only when all pass, deploys to **Azure Container Apps** with `infra/*.bicep` + `scripts/deploy/*.sh`; the deploy job waits for approval on the `azure-production` environment. Walkthrough: [docs/deployment/azure.md](../docs/deployment/azure.md) |

## integration CI

two jobs, run in order:

1. **validate + build** — runs `docker compose config` then `docker compose build`. if any image fails to build, the smoke check job never runs
2. **smoke check** — spins up the stack, retries each url up to 10 times with a 3s delay, saves logs, and tears everything down whether it passed or failed

urls checked: (*CI Validation Contract*)
- http://127.0.0.1:5000/ (frontend)
- http://127.0.0.1:5001/login (auth)
- http://127.0.0.1:5002/gardens (vgarden)
- http://127.0.0.1:5004/gardens (plant health monitoring)



logs are always saved as a github artifact (even on failure) and the stack is always torn down with `--volumes --remove-orphans` so nothing leaks between runs

## before merging (*Validation Gates*)

all three gates need to be green before you merge:

- **build gate** — all images built cleanly
- **runtime gate** — all smoke checks passed
- **human gate** — at least one teammate reviewed and there are no unresolved comments

## Amy's post-commit endpoint evidence

`plant_almanac.yml` tests two assigned backend functions using Flask's test client:

| Backend function | Route | Existing test |
| --- | --- | --- |
| `catalogue_api.search` | `GET /api/catalogue` | `test_public_catalogue_search_pages_and_literal_search` |
| `catalogue_api.plant` | `GET /api/catalogue/plant/<slug>` | `test_public_details_preserve_evidence_and_make_no_writes` |

The first checks pagination, filters, literal search and invalid input. The second
checks reference evidence, unknown records, read-only behaviour and private-chat
exclusion; it also exercises pest/disease detail routes. Tests use temporary
SQLite fixtures with MCP/RAG disabled and do not need live AI services.

The Tests job uploads `endpoints.xml`, `endpoints.log`, `regressions.xml`,
`regressions.log` and `run.json` as a 30-day artifact, including on failure where
files exist. `run.json` identifies the source SHA, tested SHA and Actions URL.
Copy the successful run URL, commit SHA and relevant results into the group report
before artifacts expire. A local pass is not proof that GitHub Actions passed.

## Yunus's post-commit endpoint evidence

`vgarden.yml` tests two assigned backend functions (`vgarden/tests/test_endpoints.py`)
using Flask's test client:

| Backend function | Route | Test |
| --- | --- | --- |
| `routes.create_garden` | `POST /gardens` | `test_create_garden_validates_input_and_persists` |
| `routes.garden_snapshot` | `GET /gardens/<id>/snapshot` | `test_garden_snapshot_returns_scoped_evidence_and_makes_no_writes` |

The first checks service-token auth, input validation, location geocoding and that
exactly one row is stored. The second checks auth, unknown gardens, the areas /
containers / plantings evidence the MCP server reads, per-garden isolation and
read-only behaviour. Tests use temporary SQLite with weather stubbed offline and do
not need live AI services. The Tests job uploads `endpoints.xml`, `endpoints.log`,
`regressions.xml`, `regressions.log` and `run.json` as a 30-day artifact.

## Release 2 workflow ownership

Each feature keeps its existing workflow:

| Student | Feature | Workflow | Status |
| --- | --- | --- | --- |
| Amy Zhou | Plant Almanac | `plant_almanac.yml` | Implemented in PR #72 |
| Guhan Sundar | Plant Health | `health.yml` | Follow-up #73 |
| Yunus Sayed | Virtual Garden | `vgarden.yml` | Implemented for #74 |

Each student's report contribution must identify their two backend functions,
meaningful tests, successful **push** run, commit SHA and saved test evidence.
Amy's passing run does not establish completion for the other students.
Docker builds in `plant_almanac.yml` depend on successful lint and endpoint/regression
validation. Deployment and agentic-loop Testing Report Review are separate work.

## cloud deployment (Release 2)

`cloud-deployment.yml` runs on every push to `main` (and by hand). Its `deploy` job
needs three gates: `lint`, `endpoint-tests` (auth, vgarden, almanac, health) and
`build-validate` (compose build + smoke). It then signs in to Azure with OIDC (no
stored credentials) and runs `scripts/deploy/azure-deploy.sh`: platform Bicep ->
image build/push -> apps Bicep -> cloud smoke test -> deployment report. The report
lands in `docs/evidence/release2/cloud-deployment/` and as a workflow artifact.
AI-Mode, MCP, RAG and the Multi-Agent Server are disabled in the cloud baseline.
One-time setup and everything else: [docs/deployment/azure.md](../docs/deployment/azure.md).

## report evidence

Downloaded test artifacts and the write-up for the report live under
`docs/evidence/release2/post-commit/<service>-<student>/`, and the pre-commit scan
reports under `docs/evidence/release2/pre-commit-<student>.md` (generated with
`python scripts/security/report.py <service> --owner "<Your Name>" --out <file>`). See
`docs/evidence/release2/README.md` for the full index by marking criterion.

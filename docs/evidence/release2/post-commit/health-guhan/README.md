# Post-commit CI/CD endpoint testing report — Plant Health (Guhan Sundar)

Release 2 criterion 4. The assigned workflow `.github/workflows/health.yml` runs, after
every push, automated tests for two endpoint functions of the Plant Health backend/API,
then the remaining suite as regressions, and keeps the evidence as a 30-day artifact
(also when a test fails). The files in this folder are that artifact, downloaded
unchanged from the successful **push** run below.

| | |
| --- | --- |
| Workflow | `Plant Health (Guhan)` — `.github/workflows/health.yml` |
| Event | `push` to `claude/plant-health-release-2-tests-1b9e16` (PR #77) |
| Commit tested | `c11bc73e82612b00ccd6b3755c7b283beab232bc` |
| Run | <https://github.com/Bageutter/Plant-Management-System/actions/runs/39560544593> |
| Jobs | Lint ✔ · Tests ✔ · Docker image builds ✔ · Compose smoke test (MCP + RAG disabled) ✔ |
| Artifact | `health-test-evidence-39560544593-1` (expires 2026-11-20) |
| Python | 3.12.15 on `ubuntu-latest` |

## The two endpoint functions

| Backend function | Route | Test | Result |
| --- | --- | --- | --- |
| `routes.create_assessment` | `POST /plant-health-records/assessments` | `test_create_assessment_validates_input_and_persists` | PASSED (0.21 s) |
| `routes.list_assessments` | `GET /plant-health-records/assessments` | `test_list_assessments_filters_pages_and_makes_no_writes` | PASSED (0.10 s) |

**`create_assessment`** — nine invalid JSON bodies and one wrong-typed upload each
answer `400` with a reason and write nothing; the local model being unreachable answers
`503` and writes nothing; the valid request answers `201` with the trimmed inputs, the
model's structured verdict and the agentic-loop summary; exactly one assessment, one loop
run and one plant title are stored and read back identically; a repeat assessment of the
same plant passes the earlier record to the model as history and reuses the title; a photo
sent as a data URL is decoded, validated, stored and served back by `/<id>/image`; an
HTMX request receives the rendered fragment.

**`list_assessments`** — empty list; newest-first order with full records; exact
`plant_ref` filter; `status` filter and its `400` for unknown values; `since` (ISO-8601,
`Z` accepted) and its `400`; `limit` clamped to 1–200 and `offset` to ≥ 0; a page past the
end is empty; image bytes never appear in the listing; repeated reads with every filter
return identical results and change no row and make no model call.

Both tests use a temporary SQLite database per test and the fake Ollama client from
`health/conftest.py`, with MCP, RAG and the Multi-Agent Server disabled, so no live AI
service is involved. Full test code: `health/tests/test_endpoints.py`.

## Files

| File | Content |
| --- | --- |
| `run.json` | workflow, owner, event, source/tested SHA, run URL, Python version, the two function names |
| `endpoints.xml` / `endpoints.log` | JUnit + console output of the two endpoint tests: **2 passed, 0 failed, 0 errors** |
| `regressions.xml` / `regressions.log` | JUnit + console output of the rest of the health suite: **60 passed, 0 failed, 0 errors** |

Later runs (for example after PR #79, which adds 13 workflow tests to the regression
suite) produce the same artifact under their own run id; regenerate this folder from the
run that lands on `main` before the report is exported.

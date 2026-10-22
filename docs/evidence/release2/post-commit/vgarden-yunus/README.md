# Post-commit CI/CD endpoint testing report — Virtual Garden (Yunus Sayed)

Release 2 criterion 4. The assigned workflow `.github/workflows/vgarden.yml` runs, after
every push, automated tests for two endpoint functions of the Virtual Garden backend/API,
then the rest of the suite as regressions, and keeps the evidence as a 30-day artifact
(also when a test fails). The files in this folder are that artifact, downloaded
unchanged from the successful **push** run on `main` below.

| | |
| --- | --- |
| Workflow | `Virtual Garden (Yunus)` — `.github/workflows/vgarden.yml` |
| Event | `push` to `main` |
| Commit tested | `1e1a85fbb37cd7d3702e1a95611c3c9779a7f18c` |
| Run | <https://github.com/Bageutter/Plant-Management-System/actions/runs/39624166823> |
| Jobs | Lint ✔ · Tests ✔ · Docker image builds ✔ (only after Lint and Tests) · Compose smoke test (MCP + RAG + Multi-Agent disabled) ✔ |
| Artifact | `vgarden-test-evidence-39624166823-1` (30 days) |
| Python | 3.12.15 on `ubuntu-latest` |

## The two assigned endpoint functions

| Backend function | Route | Test | Result |
| --- | --- | --- | --- |
| `routes.create_garden` | `POST /gardens` | `test_create_garden_validates_input_and_persists` | PASSED (0.06 s) |
| `routes.garden_snapshot` | `GET /gardens/<id>/snapshot` | `test_garden_snapshot_returns_scoped_evidence_and_makes_no_writes` | PASSED (0.08 s) |

**`create_garden`** (the server-to-server endpoint auth calls when a user adds a garden):
requests without the inter-service token are refused; invalid bodies (missing or blank
name, wrong types, bad owner) answer `400` and write nothing; a valid request answers
`201` with the trimmed fields; exactly one garden is stored for that owner and reads back
identically.

**`garden_snapshot`** (the evidence endpoint the shared MCP server and the Multi-Agent
integration read): requires the service token; a missing garden is `404`; the payload
contains only that garden's areas, containers and plantings (never another owner's), with
the evidence note; repeated reads return identical results and change no row.

The same `endpoints.xml` also contains two coverage tests added later
(`test_healthz_returns_service_status`, `test_list_gardens_filters_results_by_owner`):
**4 passed, 0 failed**. Full test code: `vgarden/tests/test_endpoints.py`.

## Files

| File | Content |
| --- | --- |
| `run.json` | workflow, owner, event, source/tested SHA, run URL, Python version, the two function names |
| `endpoints.xml` / `endpoints.log` | JUnit + console output of the endpoint tests: **4 passed, 0 failed, 0 errors** |
| `regressions.xml` / `regressions.log` | the rest of the vgarden suite: **135 passed, 0 failed, 0 errors** |
| `ai-loop-review-modes.log` | the shared agentic loop's review-mode tests, run in the same workflow |

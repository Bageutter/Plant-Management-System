# Post-commit CI/CD endpoint testing report — Plant Almanac (Amy Zhou)

Release 2 criterion 4. The assigned workflow `.github/workflows/plant_almanac.yml` runs,
after every push, automated tests for two endpoint functions of the Plant Almanac
backend/API, then the rest of the suite as regressions, and keeps the evidence as an
artifact. The files in this folder are that artifact, downloaded unchanged from the
successful **push** run on `main` below.

| | |
| --- | --- |
| Workflow | `Plant Almanac (Amy)` — `.github/workflows/plant_almanac.yml` |
| Event | `push` to `main` |
| Commit tested | `02b2deabd0a076846d6c8a71e28097426c2c005a` |
| Run | <https://github.com/Bageutter/Plant-Management-System/actions/runs/39624128438> |
| Jobs | Lint ✔ · Tests ✔ · Docker image builds ✔ |
| Artifact | `almanac-test-evidence-39624128438-1` |
| Python | 3.12.15 on `ubuntu-latest` |

## The two assigned endpoint functions

| Backend function | Route | Test | Result |
| --- | --- | --- | --- |
| `catalogue_api.search` | `GET /api/catalogue` | `test_public_catalogue_search_pages_and_literal_search` | PASSED (0.20 s) |
| `catalogue_api.plant` | `GET /api/catalogue/plant/<slug>` | `test_public_details_preserve_evidence_and_make_no_writes` | PASSED (0.20 s) |

**`search`**: pages with `limit`/`offset` without overlap (`next_offset`); matches are
case-insensitive and literal (common and scientific names); `kind` filters; queries that
must match nothing return empty lists; invalid parameters answer `400` with a reason;
paths keep the `/almanac` prefix when called through the shared reverse proxy.

**`plant`**: a plant's details include its pests, diseases and evidence note; pest and
disease guides page their linked plants and keep their sources; unknown records are
`404`; non-GET methods are refused; reads change no row and never expose private chat
data.

Full test code: `almanac/tests/test_catalogue_api.py`.

## Files

| File | Content |
| --- | --- |
| `run.json` | workflow, owner, event, source/tested SHA, run URL, Python version, the two function names |
| `endpoints.xml` / `endpoints.log` | JUnit + console output of the two endpoint tests: **2 passed, 0 failed, 0 errors** |
| `regressions.xml` / `regressions.log` | the rest of the almanac suite: **105 passed, 0 failed, 0 errors** |

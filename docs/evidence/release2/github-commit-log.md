# Release 2 GitHub commit log

Repository: <https://github.com/Bageutter/Plant-Management-System> ·
full history: <https://github.com/Bageutter/Plant-Management-System/commits/main> ·
pull requests: <https://github.com/Bageutter/Plant-Management-System/pulls?q=is%3Apr>

Release 2 began after the Release 1 submission (4 October 2026). The tables list every
Release 2 commit on `main` plus the open Release 2 pull requests at the time of writing,
grouped by student. Per-author views: append `?author=<login>` to the commits URL.

## Amy Zhou — Plant Almanac (`0melette`)

| Date | Commit | PR | Change |
| --- | --- | --- | --- |
| 2026-10-06 | `69f065e` | #66 | Add optional ChromaDB retrieval and controlled RAG MCP tools |
| 2026-10-20 | `54c0c1e` | #70 | Add shared multi-agent workflow server, audit and dashboard (Planner, Worker, Reviewer, human review, audit exports, `/dashboard`) |
| 2026-10-21 | `aed5d02` | #71 | Run security checks and feature tests before committing (shared pre-commit: Ruff S, detect-secrets, pip-audit, feature tests; `scripts/security/`) |
| 2026-10-21 | `0d330db` | #72 | Add Almanac endpoint tests and CI report evidence (`plant_almanac.yml`: `catalogue_api.search`, `catalogue_api.plant`) |

## Yunus Sayed — Virtual Garden (`yunz-dev`)

| Date | Commit | PR | Change |
| --- | --- | --- | --- |
| 2026-10-21 | `17c9cc1` | #74/#75 | ci(vgarden): post-commit tests for two assigned endpoint functions (`routes.create_garden`, `routes.garden_snapshot`) |
| 2026-10-21 | `0a31150` | #76 | feat(vgarden): Multi-Agent workflow with human review on each garden (+ `vgarden` source on the server, evidence docs) |

## Guhan Sundar — Plant Health (`Bageutter`, `WTG-Guhan-Sundar`)

| Date | Commit | PR | Change |
| --- | --- | --- | --- |
| 2026-10-21 | `c11bc73` | [#77](https://github.com/Bageutter/Plant-Management-System/pull/77) | ci(health): post-commit tests for two assigned endpoint functions (`routes.create_assessment`, `routes.list_assessments`); cross-platform pre-commit launcher |
| 2026-10-21 | `db486dc` | [#79](https://github.com/Bageutter/Plant-Management-System/pull/79) | feat(health): Multi-Agent workflow with human review on the records page; `health` source and `application_integration` helper on the server |
| 2026-10-21 | `a4a293b` | #79 | feat(multi-agent): honour `MULTI_AGENT_HOST`/`PORT` so containers on a Linux engine can reach the server |
| 2026-10-21 | `ede4cdc` | #79 | fix(multi-agent): a mangled reviewer quote flags the record for the human instead of failing the review (found on the first live Plant Health workflow) |
| 2026-10-21 | `84b233d` | [#78](https://github.com/Bageutter/Plant-Management-System/pull/78) | feat(deploy): Azure cloud deployment on check-in (`cloud-deployment.yml`, Bicep, `scripts/deploy/azure-*.sh`) |
| 2026-10-21 | (this PR) | — | Release 2 report evidence: diagrams, local deployment logs, pre-commit report, contribution logs, report draft |

Update this page when the open pull requests merge (replace the branch commit ids with
the merge commits on `main`) and before the report is exported, so the ids match what
the markers see on GitHub.

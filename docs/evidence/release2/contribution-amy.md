# Contribution log: Amy Zhou

**Confirmed by Amy Zhou on 28 October 2026.**

For Release 2, I built the shared Multi-Agent Server and connected it to the
Almanac chat, including source checks, human decisions, workflow history and the
dashboard. I added the shared security hooks and Almanac endpoint tests, improved
RAG retrieval, and made sure the cloud catalogue is populated on startup. I also
refreshed the Testing Review evidence, recorded my acceptance and added full cloud
CRUD validation. My later Almanac work shows live agent stages, readable role
outputs and explicit review choices in chat.

Release 2, Assessment 3. Feature: **Plant Almanac** (`almanac/`), plus the shared
Multi-Agent Server (`ai-services/multi-agent-server/`), the shared pre-commit security
hooks and the shared RAG server's embeddings.

| Date | Commit / PR | Criterion | Work | Evidence |
|---|---|---|---|---|
| 20 Oct | `54c0c1e` (#70) | 2 Multi-Agent | The shared non-containerised **Multi-Agent Server**: Planner, Worker and Reviewer agents, human review (accept / partially accept / request changes / reject), SQLite workflow store, audit export (`audit.py`) and read-only dashboard. | `ai-services/multi-agent-server/`, its tests |
| 21 Oct | `aed5d02` (#71) | 3 Pre-commit | **Pre-commit security hooks** for the whole repository: Ruff security rules, detect-secrets, pip-audit and the assigned feature's tests on every commit, with JSON evidence. | `.pre-commit-config.yaml`, `scripts/security/` |
| 21 Oct | `0d330db` (#72) | 4 Post-commit CI | `plant_almanac.yml` tests two endpoint functions (`catalogue_api.search`, `catalogue_api.plant`) after every push and keeps the evidence as an artifact. | [`post-commit/almanac-amy/`](post-commit/almanac-amy/) |
| 21 Oct | `fd78c05` (#86) | 1 RAG | Deterministic 256-dimension embeddings by default for the shared RAG server. | `ai-services/rag-server/` |
| 21 Oct | `045f99f` (#88) | 1–2 Multi-Agent | Almanac chat integrated with the Multi-Agent Server, with a readable human-review interface (concerns, exact/missing source facts, decision controls). | [`almanac-review/`](almanac-review/) |
| 22 Oct | `d2f37ff` (#67) | 1 | Shared Almanac chat and ailment (pest/disease) reference pages. | `almanac/` |
| 22 Oct | `aab0394` (#90) | 7 Cloud | My Garden catalogue refreshed at start-up so the cloud database is populated. | `almanac/` |
| 22 Oct | `dff9599`, `c868b79` | 8 Testing review | Refreshed the Testing review evidence and recorded the human decision (**accept**) on it. | [`testing-review.md`](testing-review.md) |
| 27 Oct | `55d82fb` (#112) | 7 Cloud | Added required full-cloud CRUD validation after deployment and preserved failed validation output so a failing check cannot appear successful. | `scripts/deploy/azure-e2e.py`, `.github/workflows/cloud-deployment.yml` |
| 27 Oct | `36a2479`, `13f9778`, `69faca0` | 1–2 Multi-Agent | Added live Almanac agent stages, explicit human-review choices, an explicit validation-loop chat mode and readable output cards for each agent. | `almanac/`, `ai-services/multi-agent-server/` |

## Evidence

- Pre-commit: [`pre-commit-amy.md`](pre-commit-amy.md)
- Post-commit CI: [`post-commit/almanac-amy/`](post-commit/almanac-amy/)
- Multi-Agent (almanac): [`almanac-review/`](almanac-review/) and
  [`almanac-multi-agent/`](almanac-multi-agent/) (terminal run and audit export)

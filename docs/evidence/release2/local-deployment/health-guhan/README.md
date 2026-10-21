# Local deployment evidence — the integrated Release 2 application (Guhan Sundar)

Criterion 1 (integrated local application and AI services) and the "logs of multi-server
system testing using multiple terminals" the report asks for. Everything below was
captured on 21 October 2026 (10:03–10:30 UTC) on one laptop (Windows 11, WSL 2 Ubuntu,
Docker Engine 29.1.3, CPU-only Ollama with 6-thread model variants), from the
`claude/release2-report-evidence` branch, which includes the Plant Health Multi-Agent
integration (PR #79).

## What ran, and where

| Terminal | Process | Containerised? | Log |
| --- | --- | --- | --- |
| 1 | `docker compose up -d --build` → proxy (nginx :3000), frontend, auth, vgarden, almanac, health, ollama | yes (Docker Compose) | [`terminal-1-compose-up.log`](terminal-1-compose-up.log), [`compose-ps.log`](compose-ps.log) |
| 2 | `MCP_HOST=0.0.0.0 python ai-services/mcp-server/server.py` → MCP server :5105 | **no** (host process) | [`terminal-2-mcp-server.log`](terminal-2-mcp-server.log) |
| 3 | `RAG_HOST=0.0.0.0 python ai-services/rag-server/app.py` → RAG server :5106 | **no** (host process) | [`terminal-3-rag-server.log`](terminal-3-rag-server.log) |
| 4 | `MULTI_AGENT_HOST=0.0.0.0 python ai-services/multi-agent-server/app.py` → Multi-Agent Server :8003 | **no** (host process) | [`terminal-4-multi-agent-server.log`](terminal-4-multi-agent-server.log) |
| 5 | Plant Health through the proxy: CRUD, four AI-Mode assessments (vision model + reviewer loop), an MCP tool run, a RAG sync and grounded answer | client (curl) | [`terminal-5-health-walkthrough.log`](terminal-5-health-walkthrough.log) |
| 6 | `bash scripts/test/multi-agent-health.sh "Tomato, back bed"` — Planner → Worker → Reviewer → Human Review through the health backend, with a request-changes round | client (curl) | [`terminal-6-multi-agent-health.log`](terminal-6-multi-agent-health.log) |
| browser | the same workflow from the *Agent workflow* panel on the records page, accepted from the review form | frontend UI | section below; [`health-workflows.json`](health-workflows.json), [`workflow_history.jsonl`](workflow_history.jsonl) |

At the time of this run `docker-compose.yml` still had an `ollama` container, so the
AI-Mode model ran there (`qwen2.5vl:3b` for the vision assessment, `qwen3:4b-instruct`
for the health reviewer, the RAG answer and all three agents) and the shared servers on
the host reached it over the compose network. `main` has since moved Ollama to the host
(`ollama serve`, reached at `host.docker.internal:11434`), matching the brief's
"non-containerised AI-Mode"; the rest of the setup is unchanged. The containers reach the
shared servers at `host.docker.internal` (`172.17.0.1` on a Linux engine, hence the
`*_HOST=0.0.0.0` settings). Nothing was sent to any third-party AI service.

### Wiring check (each backend reports its integrations)

`GET /health/plant-health-records/integrations` — [`health-integrations.json`](health-integrations.json):

```json
{"mcp": {"enabled": true, "reachable": true, "url": "http://host.docker.internal:5105/mcp"},
 "multi_agent": {"enabled": true, "reachable": true, "url": "http://host.docker.internal:8003"},
 "rag": {"enabled": true, "reachable": true, "url": "http://host.docker.internal:5106"}}
```

`GET /vgarden/integrations` — [`vgarden-integrations.json`](vgarden-integrations.json) reports the same three
URLs enabled. [`healthz-probes.log`](healthz-probes.log) has the `/healthz` answers of all
services through the proxy and of the three host servers.

## Terminal 5 — Plant Health through the proxy (AI-Mode, MCP, RAG, CRUD)

Full transcript: [`terminal-5-health-walkthrough.log`](terminal-5-health-walkthrough.log).

| Step | Call (via `http://127.0.0.1:3000/health/plant-health-records`) | Result |
| --- | --- | --- |
| Liveness | `GET /healthz` | `ok`; vision model `qwen2.5vl:3b-demo` preloaded in 5.5 s |
| AI-Mode + agentic loop | `POST /assessments` ×3 for "Tomato, back bed", ×1 for "Basil" (text only) | #1 at risk 30/100 (39 s, reviewer approved on the first pass); #2 unknown, no score (126 s: the reviewer asked for one revision, 2 iterations); #3 at risk 30/100 (37 s); #4 Basil at risk 30/100 (23 s). Every record carries its loop run id and verdict |
| CRUD read | `GET /assessments?plant_ref=Tomato, back bed&limit=5` | the three tomato records, newest first |
| MCP through the backend | `POST /tools/run` `summarise_plant_health_history` | 127 ms; 3 assessments, recurring issues *Nutrient Deficiency* ×2 and *Overwatering* ×2, score trend 30 → – → 30, with the evidence note that verdicts are advisory |
| RAG through the backend | `POST /ask/sync` then `POST /ask` "What has been wrong with the tomato in the back bed, and is it improving?" | indexed 4 documents / 16 chunks; answer in 27.8 s, confidence **medium** (2 cited passages, top relevance 76 %, model self-rating *moderate*), citing Assessment #1 (issues) and #3 (description), answered by `qwen3:4b-instruct-demo` |

The Perceive → Reason → Act → Observe → Repeat traces of the four assessments are in
[`ai-loop-health.jsonl`](ai-loop-health.jsonl) and `ai-loop-reports-health/` (one Markdown
transcript per run).

## Terminal 6 — Multi-Agent workflow through the health backend

Full transcript: [`terminal-6-multi-agent-health.log`](terminal-6-multi-agent-health.log)
(workflow `a7f23d6d`, `qwen3:4b-instruct` for all three roles). The script talks only to
the health backend; the backend read the plant's three assessments through the MCP
server (`evidence: mcp:get_health_assessment`) and sent them with the task
*"Summarise how the health of this plant has changed across its assessments and which
issues keep recurring."*

| Stage | Result |
| --- | --- |
| Planner (17 s) | 6 information-processing steps: retrieve the assessments, extract score/status per record, compare the `issues` fields, compare confidence, check persistence, summarise without diagnosing |
| Worker (38 s) | "The plant's health status remains 'at risk' in both Assessment 1 and Assessment 3, with a health score of 30/100. Issues of nutrient deficiency and overwatering recur … Assessment 2 has 'unknown' status with no health score …" citing all four passages |
| Reviewer (86 s) | `revise`, 7 issues: it checks each cited record on its own, so claims that span records ("recur across assessments", "confidence is medium in all") are flagged as unsupported by the single record; two records carry the new "not verbatim in the answer; check this record by hand" issue (the model mangled its quote) |
| Human (terminal) | `request_changes`: "Also list the health score of every assessment, oldest first." |
| Run 2: Planner (16 s) → Worker (39 s) | "Tomato, back bed — Plant Health record: Assessment 1 (oldest): health score 30/100, status at risk; issues: Nutrient Deficiency, Overwatering. Assessment 2: health score not recorded, status unknown … Assessment 3 (newest): health score 30/100 … no improvement in health score." — every fact matches the stored records |
| Run 2: Reviewer (< 1 s) | `revise`: "Remove unused citation" ×4, because the Worker labelled the paragraph with the plant name rather than each record's title, so no citation matched a paragraph |
| Human (terminal) | `partially_accept` (the cautious default when the Reviewer says revise): "Approved only the claims the Reviewer did not flag; the flagged claims remain unresolved." |

History: `received → planning → working → reviewing → awaiting_human_review →
changes_requested → planning → working → reviewing → awaiting_human_review →
partially_accepted` (10:19:57 → 10:23:19 UTC). Metrics after this and the UI run below
([`multi-agent-metrics.json`](multi-agent-metrics.json)): 2 tracked workflows, 3 agent
runs, hand-off success 9/9 stages, one human-requested revision, both workflows closed by
a human decision (1 accepted, 1 partially accepted).

**First attempt (workflow `d2416760`, 10:13 UTC) failed at the Reviewer** with
`Reviewer quoted text outside the answer`: the reviewer model had quoted the Worker's
"30/100" as "30/-100" and `reviewer.py` treated that as an invented quote, failing the
stage before any human could review (Planner 15 s and Worker 37 s had succeeded). The
fix (PR #79, `ede4cdc`: case/whitespace-insensitive matching, and a mangled quote
becomes a *check this record by hand* issue) was applied, the server restarted, and the
run above repeated. The health service's view of both workflows is in
[`health-workflows.json`](health-workflows.json) (`failed`, then `partially_accepted`).

## Frontend UI run — the same workflow from the records page

Workflow `ae71c81a` was then started from the *Agent workflow* panel at
`http://localhost:3000/health/plant-health-records/` (plant "Tomato, back bed", task
*"Which issues were recorded for this plant, and did its health score change between
assessments?"*). The panel showed "Running locally (planning)…" and polled every 3 s
through the stage badges, then rendered the Planner's six steps, the Worker's answer —
"Issues recorded: Nutrient Deficiency (medium), Overwatering (medium). Health score:
30/100 in Assessment 1 and Assessment 3; not recorded in Assessment 2 … Status changed
from at risk to unknown to at risk." (all as stored) — the Reviewer's `revise`
(four "Remove unused citation" issues, the labelling quirk described above), the evidence
sent (4 passages via `mcp:get_health_assessment`) and the review form. Because the
Reviewer said revise, the form required a reason to accept; *Accept* was submitted as
`guhan-ui` with that reason and the panel switched to **ACCEPTED** with the decision and
feedback shown under *Human review* (10:25:46 → 10:26:23 UTC). The server's dashboard
at `http://127.0.0.1:8003/dashboard` lists both workflows.

Server-side evidence of these workflows (criterion 2): [`workflow_history.jsonl`](workflow_history.jsonl)
(every event with plan, evidence, answer, review and decision),
[`coordination_audit.jsonl`](coordination_audit.jsonl) (hand-offs, model per role, decisions),
[`multi-agent-metrics.json`](multi-agent-metrics.json), and the health service's own view
[`health-workflows.json`](health-workflows.json). The Perceive → Reason → Act → Observe →
Repeat traces of the four assessments are in [`ai-loop-health.jsonl`](ai-loop-health.jsonl)
and `ai-loop-reports-health/`.

## Service logs

`compose-<service>.log` — the last 300 lines of each container's log after the run
(`proxy`, `frontend`, `auth`, `vgarden`, `almanac`, `health`, `ollama`), and
[`compose-ps-final.log`](compose-ps-final.log).

## Reproducing

```bash
# terminal 1 (repo root)
docker compose up -d --build
# terminal 2..4 (repo root; a venv with each server's requirements)
MCP_HOST=0.0.0.0 python ai-services/mcp-server/server.py
RAG_HOST=0.0.0.0 python ai-services/rag-server/app.py
MULTI_AGENT_HOST=0.0.0.0 python ai-services/multi-agent-server/app.py     # from its folder on macOS: python app.py
# terminal 5..6
open http://localhost:3000/health/plant-health-records/   # Agent workflow panel
bash scripts/test/multi-agent-health.sh "Tomato, back bed"
```

Notes from this run:

- All seven compose containers and the three host servers ran together; the health and
  vgarden `/integrations` endpoints reported MCP, RAG and Multi-Agent enabled and (for
  health) reachable. The almanac container first exited because the two-week-old
  `almanac_data` volume held a database its current migrations could not upgrade
  (`no such table: plant_images`); it was restarted on a fresh volume and served its
  catalogue (`/almanac/api/plants` 200).
- CPU inference: a text-only assessment with the reviewer loop took 23–39 s (126 s when
  the reviewer asked for a revision); an agent run (Planner + Worker + Reviewer) 1–2.5
  min; a RAG answer 28 s. 6-thread model variants were used because the default thread
  count on this hybrid-core CPU is ~80× slower.
- The Reviewer is strict rather than wrong: it checks each cited record in isolation, so
  a correct cross-record summary is still returned as `revise`, which is exactly why the
  human decision is required and why the terminal script defaults to partial acceptance.

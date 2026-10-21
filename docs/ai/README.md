# AI in the Plant Management System

This directory is the single home for how AI is designed, prompted, grounded, and
made auditable **across every microservice** in the project. It is deliberately
kept next to the code it describes; when a prompt, model, or context budget
changes, the matching page here changes in the same PR.

| Page | What it covers |
|---|---|
| [`architecture.md`](architecture.md) | Where AI sits in the system, the local-first inference stance, the Ollama topology, the model matrix, and the placeholder services that are not built yet. |
| [`context-management.md`](context-management.md) | How each service assembles the *grounding* it hands the model, the context/​history/​output budgets, retrieval and selection, caching, and truncation. |
| [`prompt-engineering.md`](prompt-engineering.md) | The full prompt catalogue with source pointers, and the techniques applied — structured output, grounding rules, prompt-injection resistance, confidence de-biasing, feedback threading. |
| [`agentic-workflow.md`](agentic-workflow.md) | The **Plan → Act → Observe → Adapt** loop: the shared runtime orchestrator, the build-time sibling, and which services use it. |
| [`mcp-rag-design.md`](mcp-rag-design.md) | **Release 1:** the shared local MCP server and RAG server, their tool/retrieval boundaries, and how the Plant Health feature reaches them through its backend. |
| [`../agentic-ai-workflow.md`](../agentic-ai-workflow.md) | The original deep-dive on the runtime loop (kept; linked from code and compose). `agentic-workflow.md` is the whole-project view that wraps it. |

## The one-paragraph version

Every model call in this project runs against a **locally hosted Ollama
instance** — no text, image, or garden data leaves the local network. Each
feature builds a **structured JSON grounding** of exactly the facts the model is
allowed to use, pins the model to a **response schema**, runs at
**`temperature` 0–0.2**, and tells the model to refuse rather than guess when the
grounding is thin. The two conversational features (Almanac chat, Virtual Garden
chat) additionally wrap the call in a **Plan → Act → Observe → Adapt** loop where
a second, independent model reviews each draft, and the Plant Health assessment
runs a **Perceive → Reason → Act → Observe → Repeat** loop of the same shape around
its vision call; every phase of every run is logged three ways for evidence.

## AI by service — the whole map

| Service | AI feature | Model call | Agentic loop | Grounding source | Doc |
|---|---|---|---|---|---|
| **`almanac/`** (Plant Almanac) | "Ask the Almanac" chat | `qwen3:4b-instruct`, JSON schema, `temp 0` | **Yes** — runtime P→A→O→A, reviewer `llama3.1:8b` | Selected plant reference records + current month + chat history | [context](context-management.md#almanac) · [prompts](prompt-engineering.md#almanac) |
| **`vgarden/`** (Virtual Garden) | "Ask about this garden" chat; **Release 1:** owner-scoped *Tools (MCP)* and *Ask about this garden, grounded (RAG)* panels routed through the backend, both strictly scoped to the authenticated garden | `qwen3:4b-instruct`, JSON schema, `temp 0` (chat); none for MCP/RAG passthrough | **Yes** (chat only) — runtime P→A→O→A, reviewer `llama3.1:8b` | One garden snapshot (areas, containers, plantings) + live weather + chat history | [context](context-management.md#vgarden) · [prompts](prompt-engineering.md#vgarden) · [mcp+rag](mcp-rag-design.md) |
| **`health/`** (Plant Health) | Photo / description health assessment (+ SSE streaming variant); **Release 1:** *Tools (MCP)* and *Ask about your records (RAG)* panels routed through the backend; **Release 2:** *Agent workflow* panel that sends one plant's stored assessments to the shared Multi-Agent Server and collects the gardener's decision (`health/workflows.py`) | `qwen2.5vl:3b` (vision), JSON schema, `temp 0.2` | **Yes** — runtime **Perceive → Reason → Act → Observe → Repeat**: code consistency checks + reviewer `qwen3:4b-instruct` | The user's photo and/or free-text description + optional `plant_ref` string + the plant's earlier assessments | [context](context-management.md#health) · [prompts](prompt-engineering.md#health) · [agentic](agentic-workflow.md#health) · [mcp+rag](mcp-rag-design.md) |
| **`auth/`** | — | none | — | — | — |
| **`shared/frontend/`** | — | none | — | — | — |
| **`tools/ai-dev/`** | Build-time repo reviewer (`./ai-dev`) | `qwen3:4b-instruct` proposes, `llama3.1:8b` reviews | **Yes** — build-time P→A→O→A, human ADAPT | Repository files in scope, capped at 16 000 chars | [agentic](agentic-workflow.md#build-time) |
| **`ai-services/mcp-server/`** (shared, local) | One MCP server for all features; Plant Health, Plant Almanac and Virtual Garden tools all implemented | none — returns structured tool results | — | Feature public HTTP APIs via the proxy (Virtual Garden's snapshot endpoints additionally require the shared service-token bearer, since garden data is private per-owner) | [design](mcp-rag-design.md#2-shared-mcp-server--ai-servicesmcp-server) |
| **`ai-services/rag-server/`** (shared, local) | Grounded answers with citations + confidence category; `health`, `almanac` and `vgarden` sources all implemented | `qwen3:4b-instruct`, JSON schema, `temp 0`; default local 256D `deterministic-256-v1` embeddings | No (relevance gate + code re-validation) | Retrieved chunks of indexed records only, optionally narrowed to one `source_id` (used by Virtual Garden so a question is never grounded in another owner's garden) | [design](mcp-rag-design.md#3-shared-rag-server--ai-servicesrag-server) |
| **`ai-services/multi-agent-server/`** (shared, local; **Release 2**) | Planner → Worker → Reviewer → Human Review workflows for `almanac` (Worker retrieves via MCP), `vgarden` and `health` (backend supplies the evidence); audit exports and dashboard | `qwen3:4b-instruct` for all three roles, JSON schemas, `temp 0–0.1` | Itself the multi-agent loop; a human decision closes every workflow | Caller-supplied passages (one garden's snapshot; one plant's stored assessments) or MCP `retrieve_context` for the Almanac | [README](../../ai-services/multi-agent-server/README.md) |
| **`ai-services/ai-mode/`**, **`ai-input/`** | Placeholder dirs | not built | — | — | [architecture](architecture.md#not-built-yet) |

## Evidence artefacts already in the repo

- `tools/ai-loop/logs/<service>.jsonl` + `tools/ai-loop/logs/reports/<service>/<run_id>.md` — every runtime loop run, phase by phase.
- `tools/ai-dev/logs/<author>.md` + `tools/ai-dev/logs/reports/<author>/NNNN-*.md` — every build-time review, accepted or rejected.
- In-product: a `🔄 Plan → Act → Observe → Adapt` badge under each chat answer, linking to `GET /…/ai/loop/<run_id>`.
- `python tools/ai-loop/view.py` — terminal replay of the runtime loop.

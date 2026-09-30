# Agentic workflow — whole-project view

The project implements **Plan → Act → Observe → Adapt** in two places that share
the same shape:

| | Runtime loop | Build-time loop |
|---|---|---|
| **Where** | `shared/ai_loop.py`, in the request path of the almanac + vgarden chats | `tools/ai-dev/pipeline.py`, run by a developer via `./ai-dev` |
| **Acts on** | A user's chat question | Repository files for one feature / the whole architecture |
| **Proposer** | `qwen3:4b-instruct` | `qwen3:4b-instruct` |
| **Reviewer** | `llama3.1:8b` (independent model) | `llama3.1:8b` (independent model) |
| **ADAPT** | Automatic — guidance threaded into the next ACT, up to `AI_LOOP_MAX_ITERATIONS` | A human accepts/rejects and may add a note |
| **Evidence** | stdout + JSONL + markdown transcript + DB row + in-product trace | markdown index + per-run report under `tools/ai-dev/logs/` |
| **Deep dive** | [`../agentic-ai-workflow.md`](../agentic-ai-workflow.md) | `tools/ai-dev/README.md` |

Both are grounded (the model only sees supplied facts) and both use a *different*
model to review than to propose.

## Which services are agentic

| Service | Loop? | Notes |
|---|---|---|
| `almanac/` chat | **Runtime P→A→O→A** | `ask_almanac()` → `ai_loop.AgenticLoop`. Falls back to single-shot if `shared/ai_loop.py` isn't mounted or the reviewer model is unreachable. |
| `vgarden/` chat | **Runtime P→A→O→A** | `garden_ai.ask()` → same orchestrator, `service="vgarden"`. Same fallback. |
| `health/` assessment | **Runtime Perceive → Reason → Act → Observe → Repeat** | `agentic.HealthAssessmentLoop` wraps the structured vision call: code consistency checks plus an independent text reviewer (`OLLAMA_REVIEW_MODEL`) observe each draft; guidance is carried into the next Reason. Falls back to checks-only if no reviewer is available. See [below](#health). |
| `auth/`, `shared/frontend/` | No AI | — |
| `tools/ai-dev/` | **Build-time P→A→O→A** | Human ADAPT. Never modifies project files. |
| `ai-services/multi-agent-server/` | Future | The placeholder for genuine multi-agent orchestration across services. |

<a id="runtime"></a>
## The runtime loop in one diagram

```
                ┌───────────────────────────────────────────────┐
                │                                               ▼
  user question ─► PLAN ──► ACT ──► OBSERVE ──► ADAPT ──► approved? ─┬─ yes ─► answer
                │            ▲          │                            │
   grounding ───┘            │      reviewer                         └─ no ─► carry
   (build_context)           │      verdict + guidance                       guidance
                             └────────────────────────────────────────────────┘
                                   loop, up to AI_LOOP_MAX_ITERATIONS (default 2)
```

- **PLAN** — `build_context()` assembles the grounding; `plan_summary` is logged.
- **ACT** — proposer drafts from grounding (+ carried feedback from iteration 2).
- **OBSERVE** — reviewer checks the draft against the *same* grounding, returns
  `{verdict, issues, guidance}`.
- **ADAPT** — `approved` → return; `revise` → thread `guidance` into the next
  ACT; cap reached → return last draft as `revised_capped`.
- **Fallback** — no reviewer configured, or reviewer unreachable → one ACT, no
  OBSERVE, logged as a `fallback` phase. A reviewer outage never breaks the chat.

Full contract, env vars, and the reviewer-prompt tuning notes are in
[`../agentic-ai-workflow.md`](../agentic-ai-workflow.md).

<a id="health"></a>
## The health service's loop: Perceive → Reason → Act → Observe → Repeat

The plant health assessment is a *structured* draft (JSON matching a schema) from a
vision model, so its loop (`health/agentic.py`) has the same shape as the chat loop
but different phase contents:

```
  photo / description / plant name ─► PERCEIVE ─► REASON ─► ACT ─► OBSERVE ─► REPEAT ─┬─ approved ─► record
  earlier assessments of the plant        │         ▲                  │                 │
  (grounding)                             │         └── guidance ──────┘◄── revise ──────┘
                                          └──────────────── up to AI_LOOP_MAX_ITERATIONS
```

- **PERCEIVE** — `perceive()` builds the grounding: the evidence line
  (`one photo and a written description` …), the description, the plant name and
  up to three earlier assessments of the same plant (context only).
- **REASON** — `OllamaClient.assess()` / `assess_stream()` draft the assessment;
  from iteration 2 the prompt carries the reviewer's guidance.
- **ACT** — the draft is normalised and clamped (`ai.normalise_result`) into the
  candidate report; the logged phase records status, score, band, confidence and
  how many issues and recommendations it proposes.
- **OBSERVE** — `observe_checks()` (deterministic: status/score band agreement, a
  photo described when none was given or denied when one was, missing
  recommendations, a "healthy" plant with a high-severity issue) and then the
  shared `ai_loop.Reviewer` with a health-specific prompt (`REVIEW_PROMPT`). The
  reviewer never sees the photo and is told so; it judges grounding and
  consistency only.
- **REPEAT** — accept, or carry `guidance` into the next REASON; cap → `revised_capped`.
- **Fallback** — no `OLLAMA_REVIEW_MODEL`, the shared module not mounted, or the
  reviewer unreachable → checks-only, verdict `fallback`. An assessment is always produced.

Evidence: the same three sinks as the chat loop (service `health` in
`tools/ai-loop/logs/`), a row in `assessment_loop_runs` linked to the record, the
`🔄 … · N iterations` badge on every report, and `GET /plant-health-records/<id>/loop`.
Tests: `health/tests/test_agentic.py` (fake vision model + scripted reviewer).

## Evidence — how to show a loop ran

```bash
python tools/ai-loop/view.py                 # recent runs, both services
python tools/ai-loop/view.py <run_id>        # full Plan/Act/Observe/Adapt trace
python tools/ai-loop/view.py --follow        # live tail
docker compose logs -f vgarden               # the same phases from the service
```

- **JSONL**: `tools/ai-loop/logs/<service>.jsonl`, one object per phase.
- **Transcript**: `tools/ai-loop/logs/reports/<service>/<run_id>.md`.
- **DB**: `ai_loop_runs` (almanac) / `garden_ai_loop_runs` (vgarden) /
  `assessment_loop_runs` (health), linked to the answer or record, with the full `trace` JSON.
- **In product**: the `🔄 Plan → Act → Observe → Adapt · N iterations` badge →
  `GET /…/ai/loop/<run_id>` renders the trace (owner-scoped).

For the build-time loop: `tools/ai-dev/logs/<author>.md` is the tracked index;
each row links to a full report with the PLAN/ACT/OBSERVE/ADAPT stage log and the
human outcome.

## Tests

| What | Where |
|---|---|
| Loop mechanics (iteration counts, feedback carry-through, cap, fallback, all 3 log sinks) | `almanac/tests/test_ai_loop.py`, `vgarden/tests/test_ai_loop.py` — fake drafter + fake reviewer, no Ollama |
| Route wiring (loop runs on `/ai/ask`, `*AILoopRun` persisted + linked, trace page owner-scoped) | `vgarden/tests/test_garden_ai.py`, `almanac/tests/test_ai_mode.py` |
| Health loop (phase order, guidance carry-through, cap, code checks forcing a revision, checks-only fallback, three sinks, `AssessmentLoopRun` per record, `phase` SSE events, trace page) | `health/tests/test_agentic.py` |
| Build-time pipeline | `tools/ai-dev/tests/test_pipeline.py` |

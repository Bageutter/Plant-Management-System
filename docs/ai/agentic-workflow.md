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
| `health/` | **No** | One structured vision call. It is *defended* (schema + `normalise_result()` re-clamping) but it does not iterate or self-review. A reviewer pass is a plausible future addition. |
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

## Evidence — how to show a loop ran

```bash
python tools/ai-loop/view.py                 # recent runs, both services
python tools/ai-loop/view.py <run_id>        # full Plan/Act/Observe/Adapt trace
python tools/ai-loop/view.py --follow        # live tail
docker compose logs -f vgarden               # the same phases from the service
```

- **JSONL**: `tools/ai-loop/logs/<service>.jsonl`, one object per phase.
- **Transcript**: `tools/ai-loop/logs/reports/<service>/<run_id>.md`.
- **DB**: `ai_loop_runs` (almanac) / `garden_ai_loop_runs` (vgarden), linked to
  the assistant message, with the full `trace` JSON.
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
| Build-time pipeline | `tools/ai-dev/tests/test_pipeline.py` |

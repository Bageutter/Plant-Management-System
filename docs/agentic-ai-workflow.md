# Agentic AI Workflow — Plan → Act → Observe → Adapt

All three conversational AI features in this project —
**Ask the Almanac** (`almanac/`), **Ask about this garden** (`vgarden/`), and
**Discuss this assessment** (`health/`) — answer through an explicit agentic loop
rather than a single model call. A second, independent model reviews every draft;
the loop revises until the reviewer approves or an iteration cap is reached. Every
phase of every run is logged for evidence. (Plant Health's *initial* assessment
uses a single streamed vision‑model call; the loop is for the follow‑up chat.)

This is the *runtime* sibling of [`tools/ai-dev/`](../tools/ai-dev/README.md),
which already runs the same four-phase loop at **build time** over repository
files (proposer `qwen3:4b-instruct`, reviewer, human ADAPT, markdown
evidence under `tools/ai-dev/logs/`).

## The loop

```
                ┌──────────────────────────────────────────────┐
                │                                              ▼
  user question ─► PLAN ──► ACT ──► OBSERVE ──► ADAPT ──► approved? ─┬─ yes ─► answer
                │           ▲          │                            │
   grounding ───┘           │      reviewer                         └─ no ─► carry
   (records / garden        │      verdict + guidance                        guidance
    snapshot / weather /    └──────────────────────────────────────────────────┘
    history)                     (loop, up to AI_LOOP_MAX_ITERATIONS)
```

| Phase | What happens | Code |
|---|---|---|
| **PLAN** | Assemble the *grounding* — the only facts the model may use: the plant records relevant to the question (almanac) or the garden snapshot + live weather (vgarden), plus recent chat history. | `build_context()` per service; `AgenticLoop._plan` |
| **ACT** | A proposer model (`OLLAMA_MODEL`, default `qwen3:4b-instruct`) drafts an answer from the grounding — and, from iteration 2, from the reviewer's guidance on the previous draft. | `OllamaAlmanacAI.draft` / `OllamaGardenAI.draft` |
| **OBSERVE** | An independent reviewer model (`OLLAMA_REVIEW_MODEL`, default `qwen3:4b-instruct`) checks the draft *against the same grounding*: is every claim supported? does it admit missing info instead of guessing? on-topic? Returns `{verdict: approved\|revise, issues, guidance}`. | `shared/ai_loop.py::Reviewer.review`, prompt `PROMPT_REVIEW` |
| **ADAPT** | `approved` → return the draft. `revise` → feed `guidance` into the next ACT and loop. Cap reached → return the last draft, marked `revised_capped`. | `AgenticLoop.run` |

The orchestrator lives in a single shared module, **`shared/ai_loop.py`**
(`AgenticLoop`, `Reviewer`, `LoopLogger`, `LoopResult`), mounted into the
`almanac`, `vgarden` and `health` containers and imported via a `../shared`
`sys.path` entry locally.

### Fallback

If `OLLAMA_REVIEW_MODEL` is unset, or the review model can't be reached/pulled,
the loop runs **single-shot** (one ACT, no OBSERVE) and logs a `fallback` phase.
A reviewer outage never breaks the chat.

### Reviewer model matters

The reviewer's usefulness depends heavily on `OLLAMA_REVIEW_MODEL`. An
instruction-tuned model that reads the JSON grounding carefully
(`qwen3:4b-instruct`, the compose default) approves well-grounded drafts on the
first pass and keeps a 10‑minute showcase moving. `llama3.1:8b` is a stricter,
slower reviewer — better for stress-testing the loop, worse for a live demo. Tune
the model and `PROMPT_REVIEW` (in `shared/ai_loop.py`) together.

## Evidence — three sinks, every phase

`LoopLogger.phase()` writes each phase to all three:

1. **stdout** — `logging.getLogger("ai_loop")`, visible in
   `docker compose logs -f vgarden` / `docker compose logs -f almanac`:
   ```
   ai_loop INFO [vgarden-20260903-101112-a1b2c3] PLAN areas=2 plantings=3 has_weather=True history_messages=0
   ai_loop INFO [vgarden-20260903-101112-a1b2c3] ACT iteration=1 carried_feedback=(none) draft_chars=214 ms=8120
   ai_loop INFO [vgarden-20260903-101112-a1b2c3] OBSERVE iteration=1 verdict=revise issues=claims frost not in forecast ms=5330
   ai_loop INFO [vgarden-20260903-101112-a1b2c3] ADAPT iteration=1 decision=revise guidance=Only mention weather...
   ai_loop INFO [vgarden-20260903-101112-a1b2c3] ACT iteration=2 carried_feedback=Only mention weather... draft_chars=180 ms=7740
   ai_loop INFO [vgarden-20260903-101112-a1b2c3] OBSERVE iteration=2 verdict=approved issues=(none) ms=4900
   ai_loop INFO [vgarden-20260903-101112-a1b2c3] ADAPT iteration=2 decision=accept
   ```
2. **JSONL** — `tools/ai-loop/logs/<service>.jsonl`, one object per phase
   (`ts`, `run_id`, `service`, `phase`, `iteration`, `verdict`, `issues`,
   `elapsed_ms`, …). Machine-readable; this is what `view.py` reads and what is
   stored on the `*AILoopRun` row (`trace` column).
3. **Transcript** — `tools/ai-loop/logs/reports/<service>/<run_id>.md`, one
   human-readable file per run: the question, each draft, each review, the adapt
   decision, the final answer.

Plus, in the app: a `🔄 Plan → Act → Observe → Adapt · N iterations · reviewed ✓`
badge under every AI answer, expandable to the per-iteration draft→verdict list
and linking to `GET /…/ai/loop/<run_id>`, which renders the full trace.

### Viewing it

```bash
python tools/ai-loop/view.py                     # recent runs (both services)
python tools/ai-loop/view.py <run_id>            # full Plan/Act/Observe/Adapt trace
python tools/ai-loop/view.py --service almanac --last 20
python tools/ai-loop/view.py --follow            # live pretty tail
docker compose logs -f vgarden                   # the same phases, live from the service
```

Runs are also persisted in the database — `ai_loop_runs` (almanac),
`garden_ai_loop_runs` (vgarden), `assessment_ai_loop_runs` (health) — linked to
the assistant chat message they produced.

## Configuration

| Env var | Default | Meaning |
|---|---|---|
| `OLLAMA_MODEL` | `qwen3:4b-instruct` | proposer (ACT) |
| `OLLAMA_REVIEW_MODEL` | `qwen3:4b-instruct` | reviewer (OBSERVE); empty ⇒ single-shot |
| `AI_LOOP_MAX_ITERATIONS` | `2` | max ACT/OBSERVE rounds |
| `AI_LOOP_LOG_DIR` | `tools/ai-loop/logs` (`/app/ai_loop_logs` in compose) | JSONL + transcripts |
| `OLLAMA_AUTO_PULL` | `true` (compose) | pull both models on first use |

`docker-compose.yml` mounts `./shared/ai_loop.py` and `./tools/ai-loop/logs` into
the `almanac`, `vgarden` and `health` services and sets the env above. Health also
has `OLLAMA_CHAT_MODEL` (its follow‑up chat model, default `qwen3:4b-instruct` —
separate from the `qwen2.5vl:3b` vision model that does the assessment).

## How this satisfies "Agentic AI Workflow: Plan → Act → Observe → Adapt"

- **Plan** and **Act** and **Observe** and **Adapt** are named methods /
  logged phases in `shared/ai_loop.py` — the control flow *is* the workflow.
- The agent **acts on feedback**: the OBSERVE verdict + guidance from a rejected
  draft is threaded back into the next ACT (`carried_feedback` in the logs).
- It is **autonomous within bounds**: it iterates on its own up to
  `AI_LOOP_MAX_ITERATIONS` and reports honestly when it couldn't satisfy the
  reviewer (`revised_capped`).
- Every run is **auditable end to end** — stdout, JSONL, markdown transcript, DB
  row, and an in-product trace view — so the loop can be shown to have run.

## Tests

- `shared/ai_loop.py`: `almanac/tests/test_ai_loop.py`, `vgarden/tests/test_ai_loop.py`
  (fake drafter + fake reviewer) — iteration counts, feedback carry-through,
  iteration cap, the fallback path, and that all three log sinks are written.
- Route wiring: `vgarden/tests/test_garden_ai.py`, `almanac/tests/test_ai_mode.py`,
  `health/tests/test_chat.py` — the loop runs on the chat endpoint, an
  `*AILoopRun` is persisted and linked, history is carried across turns, and the
  trace page is scoped to the owning entity.

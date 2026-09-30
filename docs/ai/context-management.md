# Context management

Every AI feature in this project follows the same discipline: **decide, in code,
the exact set of facts the model is allowed to use; serialise them as JSON;
bound their size; and tell the model that this JSON is the whole world.** The
model is never handed raw database rows, never handed the full table, and never
allowed to fall back on its own training data for project facts.

This page documents, per service, what goes into that context, how it is
selected, and every budget that bounds it.

## The shared shape

Each conversational service exposes a `build_context()` that returns
`(grounding, plan_summary)`:

- **`grounding`** — the JSON dict the model sees. This is the contract.
- **`plan_summary`** — small integers/booleans about the grounding
  (`areas=2 plantings=3 has_weather=True`) logged as the PLAN phase, so an
  auditor can see *how much* context a given answer had without dumping the
  content.

`grounding` is built fresh on every ACT iteration (it is a closure, re-run each
loop pass) so that a long loop never drifts onto stale data.

---

<a id="almanac"></a>
## Almanac chat (`almanac/`)

**Entry:** `POST /ai/ask` → `ask_almanac()` in `almanac/app.py`.

### What goes in the grounding

```jsonc
{
  "current_month": "September",          // datetime.now().strftime("%B")
  "plant_records": [ /* selected PlantReference.to_dict() */ ],
  "conversation": [ {"role": "...", "content": "..."} ]   // recent history
}
```

### Selection / retrieval

`_records_for_question(question, all_records)` (`almanac/app.py`) is a
deliberately simple lexical filter, **not** a vector search:

- Keep any plant whose `slug`, `common_name`, or `scientific_name` appears
  (case-insensitively) as a substring of the question.
- **If nothing matches, fall back to the entire table** (`return matches or records`).

The Almanac dataset is a small, seeded reference set, so "send everything" is a
safe default. A real RAG retriever is the job of the future
`ai-services/rag-server/` (see [architecture](architecture.md#not-built-yet)).

`plan_summary` records `plant_records` (sent), `of_total` (table size), and
`history_messages` so you can see when the fallback fired.

### Budgets

| Bound | Value | Where |
|---|---|---|
| Question length | 500 chars, rejected with 400 | `almanac/app.py` |
| Chat history sent | last **20** messages | `CHAT_HISTORY_LIMIT`, `_chat_history()` |
| Draft answer length | truncated to **2000** chars | `OllamaAlmanacAI.draft` (`answer.strip()[:2000]`) |
| Reviewer output | `num_predict` 300 tokens | `shared/ai_loop.py::Reviewer` |
| `temperature` | 0 | `almanac/ai.py` |

### History caveat

History is stored per authenticated owner (`owner_key`) and **is** passed into
the grounding as `conversation`. (The service README's older line about history
"not being sent back to Ollama" is out of date for the loop path.)

### Sources

After the answer is produced, `sources_for_text(answer, plants)` re-scans the
final text for plant names and renders them as "Almanac sources" links. This is
done *outside* the model — no second structured field is threaded through the
loop for it.

---

<a id="vgarden"></a>
## Virtual Garden chat (`vgarden/`)

**Entry:** `POST /gardens/<id>/ai/ask` → `garden_ai.ask()` in `vgarden/garden_ai.py`.

### What goes in the grounding

```jsonc
{
  "garden": {
    "name": "...", "description": null, "location_label": null,
    "climate_zone": null,
    "coordinates": {"latitude": ..., "longitude": ...} | null,
    "weather": { /* compact snapshot, see below */ } | null,
    "areas":      [ {"name", "type", "notes"} ],
    "containers": [ {"name", "type", "area"} ],
    "plantings":  [ {"crop_name", "quantity", "lifecycle_state",
                     "growth_stage", "planted_date", "expected_harvest_date",
                     "location"} ]
  },
  "conversation": [ {"role", "content"} ]
}
```

Built by `_garden_snapshot(garden)`. Only **one garden** is ever in scope — the
one in the URL, after `require_garden_owner`. Cross-garden data is impossible by
construction.

### Weather sub-context

`_weather_context(garden)` → `weather.garden_weather(lat, lon)`
(`vgarden/weather.py`):

- Returns `None` (never raises into the chat) if the garden has no coordinates or
  Open-Meteo is unreachable. The prompt tells the model to say so and point the
  owner at the location setting.
- The snapshot is **condensed at the source**: `current` is 6 fields
  (temp, feels-like, humidity, precip, wind, conditions text), `forecast` is
  `forecast_days` (7) daily rows of 5 fields each. Raw Open-Meteo hourly arrays
  are never included.
- **Cached** per rounded (2 dp) coordinate for `cache_ttl` = 1800 s, so a burst
  of chat messages makes at most one upstream call.

### Budgets

| Bound | Value | Where |
|---|---|---|
| Question length | `MAX_QUESTION_LENGTH` = 500 chars | `vgarden/garden_ai.py` |
| Chat history sent | `CHAT_HISTORY_LIMIT` = **20** messages | `vgarden/garden_ai.py` |
| Draft answer length | **2000** chars | `OllamaGardenAI.draft` |
| Weather cache TTL | 1800 s | `vgarden/weather.py` |
| Forecast horizon | 7 days | `WeatherClient.forecast_days` |
| `temperature` | 0 | `vgarden/ai.py` |

`plan_summary`: `areas`, `containers`, `plantings`, `has_weather`,
`history_messages`.

---

<a id="health"></a>
## Plant Health assessment (`health/`)

**Entry:** `POST /plant-health-records/assessments` (and `.../stream` for SSE)
→ `OllamaClient.assess()` / `.assess_stream()` in `health/ai.py`.

No conversation, no database context. The "context" is purely what the user
submitted this request:

| Input | Handling |
|---|---|
| Photo | **Downscaled to `IMAGE_MAX_EDGE` = 896 px longest edge** before inference (vision models tile images into patches; full phone-resolution costs tokens for no diagnostic gain). Only the reduced image (~75 KB) is persisted. |
| Description | Free text, length-clamped (`_clean(..., max_chars, field)` in `routes.py`). |
| `plant_ref` | Optional free-form string, stored verbatim, passed to the prompt as *"the gardener refers to this plant as: …"*. Not resolved against vgarden. |

### The evidence-declaration technique

Every prompt begins with an explicit line stating exactly what the model was
given — `EVIDENCE PROVIDED: a written description only, and no photo.` — because
an earlier version fabricated *"the photo is blurry"* for text-only requests.
See [prompt-engineering](prompt-engineering.md#health) for why this matters.

### Budgets

| Bound | Value | Env |
|---|---|---|
| Context window | `num_ctx` = 4096 | `OLLAMA_NUM_CTX` |
| Output tokens | `num_predict` = 700 | `OLLAMA_NUM_PREDICT` |
| Response list caps | ≤ 4 issues, ≤ 4 recommendations, ≤ 4 missing-info items | `MAX_LIST_ITEMS`, enforced in prompt *and* in `normalise_result()` |
| Text field length | < 200 chars each (prompt-instructed) | — |
| Upload size | `MAX_UPLOAD_BYTES` = 12 MiB, else 413 | `health/config.py` |
| Image longest edge | `IMAGE_MAX_EDGE` = 896 px | `IMAGE_MAX_EDGE` |
| Inference timeout | 180 s | `OLLAMA_TIMEOUT` |
| `temperature` | 0.2 | `health/ai.py` |
| Model resident | `keep_alive` = 30m | `OLLAMA_KEEP_ALIVE` |

### Defence in depth

The schema is enforced by Ollama (`format=RESPONSE_SCHEMA`), **and then**
`normalise_result()` re-clamps every field in code: status → enum or `unknown`,
`health_score` → 0–100 int (or `None` when `unknown`), `confidence` → level or
`None`, lists sliced to `MAX_LIST_ITEMS`. The model's structured output is
treated as untrusted.

---

<a id="build-time"></a>
## Build-time reviewer (`tools/ai-dev/`)

`pipeline.py` assembles repository files as context:

- **Scope-filtered** — `--scope frontend|vgarden|almanac|health|architecture`
  restricts to that service's path prefixes (`SCOPES`).
- **Discovered** from `git ls-files` (tracked + untracked, respecting
  `.gitignore`), excluding `.git`, `.venv`, `__pycache__`, `node_modules`, and
  any `.env*`.
- **Budgeted at `MAX_CONTEXT_CHARS` = 16 000** — files are added in priority
  order until the next one would blow the budget, then skipped.
- Model call uses `num_ctx` 8192, `num_predict` 700, `temperature` 0.1.

Every cited path in the model's output is validated against the actual set of
inspected files (`validate_finding`) — the model cannot reference a file it
wasn't shown.

---

## Checklist for adding a new AI feature

1. Write a `build_context()` that returns `(grounding_dict, plan_summary_dict)`.
2. Put **only** decided facts in `grounding`; never a raw ORM object, never the
   full table unless it is provably small.
3. Bound: input length, history depth, retrieved-item count, `num_ctx`,
   `num_predict`, output length.
4. Serialise sub-contexts (weather, etc.) condensed *at the source*, with a
   cache and a never-raise fallback.
5. Re-validate / re-clamp the model's structured output in code.
6. Add a section here and a row to [`README.md`](README.md).

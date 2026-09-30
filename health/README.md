# Plant Health Monitoring Service

Analyses a plant from a **photo**, a **text description**, or both, and reports whether the
plant looks healthy plus what should be done to improve its health.

All inference runs against a **locally hosted model** (Ollama) — no image or description
leaves the local network.

> **Scope note:** this service does not currently query the Virtual Garden or Plant Almanac
> services. The mapping between an assessed plant and a plant in the Virtual Garden has not
> been decided yet, so callers pass a free-form `plant_ref` string that the service simply
> stores alongside the assessment.

## Running

With docker compose from the repository root:

```bash
docker compose up --build health
```

* UI: <http://localhost:5003/plant-health-records>
* Ollama: <http://localhost:11434>

The first assessment triggers a model pull (~3 GB), so it can take several minutes.
To avoid that wait, pull the model up front:

```bash
docker compose exec ollama ollama pull qwen2.5vl:3b
```

### GPU acceleration (strongly recommended)

By default Ollama runs on **CPU**, which is roughly an order of magnitude slower.
If the host has an NVIDIA GPU and the NVIDIA Container Toolkit installed:

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up
```

## Performance

Inference speed is dominated by three things: model size relative to available
VRAM, whether the model is already resident in memory, and image resolution.

Measured on this project's workload (RTX PRO 2000, 8 GB VRAM):

| Model | Size | Cold | Warm | Warm + photo | Valid JSON |
| --- | --- | --- | --- | --- | --- |
| `gemma4:latest` | 8.9 GB | 85.9s | 19.7s | 26.6s | yes |
| `gemma3:4b` | 3.1 GB | 20.1s | 6.2s | 9.5s | yes |
| **`qwen2.5vl:3b`** (default) | **3.0 GB** | **16.1s** | **4.4s** | **6.1s** | **yes** |
| `moondream` | 1.6 GB | 18.3s | 5.9s | 3.2s | **no** — unreliable on text-only |

`qwen2.5vl:3b` is the default: it was the fastest model that still produced valid
structured output in every case. `moondream` is smaller but failed to return usable
JSON for text-only requests, so it is not recommended.

**A model larger than available VRAM is the single biggest cause of slowness.**
`gemma4:latest` at 8.9 GB does not fit in 8 GB of VRAM, so it spills to CPU and runs
4-5x slower than a 3 GB model that fits entirely on the GPU.

Other optimisations applied automatically:

* **Model is preloaded at startup** — as soon as the service starts, a background
  thread pulls the model if needed and asks Ollama to load it (a chat request with no
  messages, Ollama's documented preload). The first assessment is therefore warm instead
  of paying the cold load. Startup is never blocked: if Ollama is still coming up the
  load is retried (`OLLAMA_PRELOAD_RETRIES` × a growing delay from
  `OLLAMA_PRELOAD_RETRY_SECONDS`), and `GET /healthz` reports the state under
  `ai.preload.status` (`pending` → `loading` → `loaded`, or `retrying` / `failed`).
  Set `OLLAMA_PRELOAD=false` to turn it off.
* **Model stays resident** — `OLLAMA_KEEP_ALIVE=30m` avoids a 7-40 second reload on
  each request. Cold vs warm is the difference between ~16s and ~4s.
* **Photos are downscaled** to `IMAGE_MAX_EDGE` (896px) before inference. Vision models
  tile images into patches, so full-resolution phone photos cost many extra tokens for
  no extra diagnostic value.
* **Output is capped** via `OLLAMA_NUM_PREDICT`, and the prompt limits the response to
  4 issues and 4 recommendations.

To trade accuracy for more speed, lower `IMAGE_MAX_EDGE` (e.g. `672`) or
`OLLAMA_NUM_PREDICT`.

Running outside docker:

```bash
cd health
pip install -r requirements.txt
cp .env.example .env   # point OLLAMA_URL at your local Ollama
python app.py
```

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | SQLite in `health/instance/health.db` | Assessment storage |
| `AUTH_PUBLIC_URL` | `http://localhost:5001` | Browser-facing auth URL for nav links |
| `OLLAMA_URL` | `http://localhost:11434` | Local AI endpoint (`http://ollama:11434` in compose) |
| `OLLAMA_MODEL` | `qwen2.5vl:3b` | Vision-capable model used for image + text analysis |
| `OLLAMA_TIMEOUT` | `180` | Inference timeout, seconds |
| `OLLAMA_AUTO_PULL` | `true` | Pull the model on first use if missing |
| `OLLAMA_PULL_TIMEOUT` | `1800` | Model pull timeout, seconds |
| `OLLAMA_KEEP_ALIVE` | `30m` | How long the model stays loaded between requests |
| `OLLAMA_NUM_PREDICT` | `700` | Maximum generated tokens |
| `OLLAMA_NUM_CTX` | `4096` | Context window |
| `OLLAMA_PRELOAD` | `true` | Load the model in the background at startup |
| `OLLAMA_PRELOAD_RETRIES` | `12` | Preload attempts while Ollama is still starting |
| `OLLAMA_PRELOAD_RETRY_SECONDS` | `5` | Initial delay between attempts (grows ×1.5, capped at 60s) |
| `MAX_UPLOAD_BYTES` | `12582912` | Maximum accepted image size (keep `client_max_body_size` in `nginx.conf` above it) |
| `IMAGE_MAX_EDGE` | `896` | Photos are downscaled to this longest edge before inference |

## How the health score works

`health_score` is a 0-100 rating where 100 is a thriving plant and 0 is a dead one.
It is the model's overall judgement of the condition it describes — not a measurement.
The prompt anchors it to fixed bands so the number stays consistent with `status`:

| Score | Band | Meaning |
| --- | --- | --- |
| 85-100 | Thriving | Routine care only |
| 60-84 | Minor issues | Easily corrected |
| 30-59 | At risk | Will worsen without action |
| 0-29 | Severe | Dying or dead |

When `status` is `unknown` the score is `null`, because there isn't enough
evidence to rate the plant. In the UI the number is accompanied by a progress bar, the
band label, and a **tooltip** (hover or keyboard focus) giving the full scale, so it is
never presented as a bare, unexplained figure.

### Why there is no confidence score

An earlier version asked the model for a numeric confidence (`0.0`-`1.0`). Self-reported
numeric confidence is not a calibrated probability — it is just another generated token,
and it came back at or near 100% regardless of how thin the evidence was.

Confidence is now reported by the model as one of **low / medium / high**, together with a
required `confidence_reason` explaining what specifically limits or supports it. Removing
the false precision, requiring a justification, and telling the model explicitly which
evidence it received (see below) makes the value far harder to inflate.

It is still a self-assessment, not a calibrated probability, and the UI says so in its
tooltip. Treat it as a rough signal.

### Evidence grounding

Every request tells the model exactly what it was given:

```text
EVIDENCE PROVIDED: a written description only, and no photo.
```

Without this the model would fabricate justifications — an early version replied *"the
photo is blurry"* for a text-only request, parroting an example from the prompt. The model
is now instructed never to describe a photo it wasn't given (it may only say one would
help), and never to deny a photo it was given.


## API

All user-facing pages and the assessment API live under `/plant-health-records`.
`GET /` redirects there, and `/healthz` stays at the root for infrastructure probes.

### `POST /plant-health-records/assessments`

Accepts `application/json` or `multipart/form-data`. At least one of the image or the
description must be supplied.

JSON fields: `plant_ref` (optional), `description` (optional), `image_base64` (optional,
raw base64 or a `data:` URL).
Form fields: `plant_ref`, `description`, `image` (file upload).

```bash
curl -X POST http://localhost:5003/plant-health-records/assessments \
  -H 'Content-Type: application/json' \
  -d '{"plant_ref":"Tomato in the back bed","description":"Planted 6 weeks ago, lower leaves turning yellow, watered daily, soil stays wet."}'
```

Responds `201` with:

```json
{
  "id": 1,
  "plant_ref": "Tomato in the back bed",
  "status": "at_risk",
  "health_score": 30,
  "score_band": "At risk — will worsen without action",
  "confidence": "medium",
  "confidence_reason": "The description covers watering and soil but no photo was provided.",
  "duration_ms": 6600,
  "plant_identification": "Tomato (Solanum lycopersicum)",
  "summary": "Lower-leaf yellowing with constantly wet soil suggests overwatering.",
  "issues": [
    {"name": "Overwatering", "severity": "medium", "evidence": "Soil stays wet, daily watering"}
  ],
  "recommendations": [
    {"action": "Reduce watering frequency", "priority": "high", "details": "Water only when the top 3cm of soil is dry."}
  ],
  "missing_information": ["A photo of the affected leaves"],
  "created_at": "2026-08-28T05:30:00+00:00"
}
```

`status` is one of `healthy`, `at_risk`, `unhealthy`, `unknown`. When `status` is
`unknown`, `health_score` and `score_band` are `null`. `confidence` is `low`, `medium`
or `high`.

Errors: `400` for invalid/missing input, `413` when the image exceeds the size limit,
`503` when the local AI instance is unreachable or the model cannot be pulled.

A `413` carries the reason and the limit: `{"error": "The upload is larger than the 12 MB
limit. ...", "limit_bytes": 12582912}`. On the streaming endpoint the same reason is sent
as a single `error` event, so a stream consumer sees it too.

### Oversized photos

`MAX_UPLOAD_BYTES` (12 MiB) is the app's limit, and `nginx.conf` allows `13m` on the
`/health/` route so the app — not the proxy — is the one that answers. The upload form
states the limit under the file picker, shows the chosen photo's size, and when a photo is
over the limit it re-encodes it in the browser to `IMAGE_MAX_EDGE` pixels (the resolution
the server downscales to anyway) before sending. A response that is not an event stream
(the app's or the proxy's `413`, an error page) is turned into a visible message rather
than being read as an empty stream. Nothing is sent anywhere but this service.

### `POST /plant-health-records/assessments/stream`

Same inputs, but responds with `text/event-stream` so the UI can show progress while the
model works. Each event is a JSON object on a `data:` line:

| Event | Fields | Meaning |
| --- | --- | --- |
| `progress` | `field`, `summary`, `chars`, `elapsed_ms` | Which part of the answer is being written, and the summary text so far |
| `done` | `id`, `html` | Finished; the rendered assessment card and its record id |
| `error` | `message` | Validation failure or the local AI being unavailable |

The stream ends after exactly one `done` or `error` event. `summary` is extracted from
partially-generated JSON, so the summary appears word by word as it is written.

### `PATCH` / `PUT /plant-health-records/assessments/<id>`

Edits the context recorded against a report: `plant_ref` and `description`. Accepts
`application/json` or form encoding. `PATCH` moves only the fields supplied; `PUT`
replaces both, so an omitted field is cleared.

```bash
curl -X PATCH http://localhost:5003/plant-health-records/assessments/1 \
  -H 'Content-Type: application/json' \
  -d '{"plant_ref":"Tomato, back bed (east end)"}'
```

Responds `200` with the updated record, or the re-rendered submission fragment for an
HTMX request. `400` if a field is not a string or exceeds its length limit (200
characters for `plant_ref`, 4000 for `description`), `404` if the record does not exist.

The AI verdict itself is deliberately not editable: it is the output of a past model run,
and rewriting it would misrepresent what the model actually said. Regenerate instead.

### `POST /plant-health-records/assessments/<id>/regenerate`

Runs the model again over the record's stored photo and its *current* description and
name, so a report can be re-issued after the context is corrected — or simply for a
second opinion.

The existing report is never overwritten: the rerun is saved as a new record and returned
with `201`, so the two runs can be compared side by side. In the UI each rerun is appended
below the report already on the page.

`400` if the record has neither a description nor a stored photo (records created before
photos were persisted), `404` if it does not exist, `503` if the local AI is unreachable.

`POST /plant-health-records/assessments/<id>/regenerate/stream` is the `text/event-stream`
variant, emitting the same events as `/assessments/stream`.

### Other endpoints

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/plant-health-records/` | UI: submit a plant, plus the list of past records |
| `GET` | `/plant-health-records/<id>` | Full record: photo, name, description and assessment |
| `GET` | `/plant-health-records/<id>/image` | The photo the assessment was based on |
| `GET` | `/healthz` | Liveness, local AI reachability, and the model preload state |
| `GET` | `/plant-health-records/assessments?plant_ref=&limit=` | List assessments, newest first |
| `GET` | `/plant-health-records/assessments/<id>` | Fetch a single assessment as JSON |
| `PATCH` | `/plant-health-records/assessments/<id>` | Edit the plant name and description |
| `PUT` | `/plant-health-records/assessments/<id>` | Replace the plant name and description |
| `POST` | `/plant-health-records/assessments/<id>/regenerate` | Assess the same inputs again as a new record |
| `DELETE` | `/plant-health-records/assessments/<id>` | Delete an assessment |

Every one of these is reachable from the UI as well as the API: records are deleted from
the row in the list or from the record page, the name and description are edited in place
on the record page, and "Generate report again" streams a fresh assessment below the
existing one.

Uploaded photos **are** persisted, at the reduced resolution actually used for inference
(typically ~75 KB), so a past record can be reviewed alongside the photo it was based on.
The full-resolution original is never stored.

## Release 1: MCP and RAG through this backend

The records page has two extra panels. Neither talks to a shared server from the
browser; both go through routes on this service, so the integration can be switched off
per deployment (CI runs with both off).

| Route | Purpose |
| --- | --- |
| `GET /plant-health-records/integrations` | `{"mcp": {enabled, url, reachable}, "rag": {...}}`. `reachable` is `null` when a mode is disabled — nothing is probed. |
| `GET /plant-health-records/tools` | Tools registered on the shared MCP server, flagged `health: true` for ours. |
| `POST /plant-health-records/tools/run` | Run **one whitelisted Plant Health tool** (`tool` + its arguments, JSON or form). Arguments are validated here before anything is sent; non-health tools are refused with `400`. Returns the structured result as JSON, or a rendered fragment for HTMX. A tool-level failure (e.g. record not found) is `200` with `is_error: true` and the tool's message — the tool ran, it just had nothing to return. |
| `POST /plant-health-records/ask` | Ask the shared RAG server a `question` (≤ 500 chars) restricted to the `health` source. Returns the RAG contract (`answer`, `confidence` ∈ high/medium/low/insufficient, `citations[]`, `insufficient_context`) or the `_rag_answer.html` fragment with the confidence badge, cited records and the insufficient-context state. |
| `POST /plant-health-records/ask/sync` | Ask the RAG server to re-index this service's assessments. |

Status codes: `400` bad input, `503` when the mode is disabled (`MCP_ENABLED=false` /
`RAG_ENABLED=false`), `502` when the shared server is unreachable or failed.

| Variable | Default | Purpose |
| --- | --- | --- |
| `MCP_ENABLED` | `true` | Switch for the tools panel/routes |
| `MCP_SERVER_URL` | `http://127.0.0.1:5105/mcp` (`http://host.docker.internal:5105/mcp` in compose) | Shared MCP server |
| `RAG_ENABLED` | `true` | Switch for the ask panel/routes |
| `RAG_SERVER_URL` | `http://127.0.0.1:5106` (`http://host.docker.internal:5106` in compose) | Shared RAG server |
| `INTEGRATION_TIMEOUT` | `180` | Seconds per call to a shared server |

The list endpoint gained `status=`, `since=` (ISO-8601) and `offset=` so the shared
servers can filter and page through records.

### Tests and CI

```bash
cd health
pip install -r requirements-dev.txt
python -m pytest -q
```

Tests use a fake model. The MCP tests run the real shared server in-process and route
its HTTP calls back into the Flask app under test, so a tool run exercises the whole
frontend → backend → MCP server → health API loop. `.github/workflows/health.yml` runs
lint, these tests, the image build, and a compose smoke test
(`scripts/test/smoke-health.sh`) with `MCP_ENABLED=false RAG_ENABLED=false`.

## Database schema changes

The service has no migration tool — SQLite is the documented development default, and
`db.create_all()` creates missing *tables* but never alters existing ones. A database
created by an older build therefore kept its old columns, and every query failed with
`no such column: assessments.image_data`.

On startup the service now compares each mapped table against the live database and adds
any missing columns with `ALTER TABLE ... ADD COLUMN` (see [schema.py](schema.py)). This
is deliberately limited:

* It only **adds** columns. It never drops or retypes them — that needs a real migration
  tool, and silently discarding data at startup would be worse than a stale column.
* Added columns are nullable, so existing rows keep their data and simply have no value
  for the new fields.
* It is idempotent; a second run adds nothing.

Because of this, upgrading no longer requires deleting `health/instance/health.db`.

One consequence worth knowing: rows written before `confidence` became a graded level
stored a float (e.g. `0.7`) in that column. Those values are not valid levels, so they are
reported as "no confidence recorded" rather than rendered as a meaningless `0.7` badge.

**This is a stop-gap, not the intended long-term solution.** It keeps no history, cannot
express a destructive change, and covers only this service — `auth` and `vgarden` still
use bare `db.create_all()` and will hit the same problem when their models change.
Replacing it with Flask-Migrate/Alembic across all services is tracked in
[issue #10](https://github.com/Bageutter/Plant-Management-System/issues/10).

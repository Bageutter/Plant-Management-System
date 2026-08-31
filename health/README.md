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

* UI: <http://localhost:5003/>
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
| `MAX_UPLOAD_BYTES` | `12582912` | Maximum accepted image size |
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

When `status` is `unknown` the score is set to `null`, because there isn't enough
evidence to rate the plant. The UI shows the band label and the scale alongside the
number so it is never presented as a bare, unexplained figure.

### Why there is no confidence score

An earlier version asked the model to report its own confidence. Self-reported LLM
confidence is not a calibrated probability — it is just another generated token, and it
tended to come back at or near 100% regardless of how thin the evidence was, which is
actively misleading. It has been removed. Instead the service reports the facts it
actually knows: which inputs the assessment was based on (photo, description, or both)
and what extra information would improve it (`missing_information`).


## API

### `POST /assessments`

Accepts `application/json` or `multipart/form-data`. At least one of the image or the
description must be supplied.

JSON fields: `plant_ref` (optional), `description` (optional), `image_base64` (optional,
raw base64 or a `data:` URL).
Form fields: `plant_ref`, `description`, `image` (file upload).

```bash
curl -X POST http://localhost:5003/assessments \
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
`unknown`, `health_score` and `score_band` are `null`.

Errors: `400` for invalid/missing input, `413` when the image exceeds the size limit,
`503` when the local AI instance is unreachable or the model cannot be pulled.

### Other endpoints

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/` | HTMX/Alpine UI for submitting a photo or description |
| `GET` | `/healthz` | Liveness plus local AI reachability |
| `GET` | `/assessments?plant_ref=&limit=` | List assessments, newest first |
| `GET` | `/assessments/<id>` | Fetch a single assessment |
| `DELETE` | `/assessments/<id>` | Delete an assessment |

Images are used for inference and are **not** persisted; only the fact that an image was
supplied and its MIME type are stored.

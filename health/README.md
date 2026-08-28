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

The first assessment triggers a model pull (a few GB), so it can take several minutes.
To avoid that wait, pull the model up front:

```bash
docker compose exec ollama ollama pull gemma3:4b
```

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
| `OLLAMA_MODEL` | `gemma3:4b` | Vision-capable model used for image + text analysis |
| `OLLAMA_TIMEOUT` | `180` | Inference timeout, seconds |
| `OLLAMA_AUTO_PULL` | `true` | Pull the model on first use if missing |
| `OLLAMA_PULL_TIMEOUT` | `1800` | Model pull timeout, seconds |
| `MAX_UPLOAD_BYTES` | `12582912` | Maximum accepted image size |

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
  "health_score": 55,
  "confidence": 0.7,
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

`status` is one of `healthy`, `at_risk`, `unhealthy`, `unknown`.

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

# Showcase runbook — Release 0

Everything below runs from **one machine**. Budget ~30 min of setup before recording.

## 1. Prerequisites

- Docker + Docker Compose
- ~12 GB free disk for the AI models
- A GPU is strongly recommended (CPU inference is ~10× slower). With an NVIDIA
  GPU + the Container Toolkit, use the `-f docker-compose.gpu.yml` override below.

## 2. Clean start (do this every time)

The demo data seeds **only into an empty database**, and it aligns ids across
services, so always start from clean volumes:

```bash
docker compose down -v
docker compose up --build -d          # add: -f docker-compose.yml -f docker-compose.gpu.yml   for GPU
```

Wait for all 7 containers:

```bash
docker compose ps          # proxy, frontend, auth, vgarden, almanac, health, ollama
```

## 3. Pull the models (once per machine — the volume caches them)

```bash
docker compose exec ollama ollama pull qwen3:4b-instruct   # chat + reviewer  (~2.6 GB)
docker compose exec ollama ollama pull qwen2.5vl:3b        # health vision    (~3.0 GB)
```

(If you skip this, the first question to each feature pulls the model live — a
few minutes of dead air. `OLLAMA_AUTO_PULL=true` makes it work either way.)

## 4. Pre-warm the models (right before recording)

The first call after a model loads is slow; keep them resident:

```bash
docker compose exec ollama ollama run qwen3:4b-instruct "hi" --keepalive 60m
docker compose exec ollama ollama run qwen2.5vl:3b "hi" --keepalive 60m
```

Then send one throwaway question to each feature so the app-level model check is
warm too.

## 5. Log in

Open **http://localhost:3000** → **Log in**:

```
email:    demo@plant.test
password: demogarden
```

The demo account already owns 12 gardens; garden 1 ("Backyard Beds") is fully
populated, and every feature has seed data.

## 6. What each person demonstrates (≤ 10 min total)

| Time | Presenter | Steps |
|---|---|---|
| 0:00 | any | `http://localhost:3000` — the home page links to all three features. `docker compose ps` (7 up). Show one green GitHub Actions run. |
| ~3 min | **Yunz — Virtual Garden** (`/vgarden/`) | Open garden 1. **CRUD**: add an area → add a container in it → add a planting → edit the planting → delete it. Open **"Ask about this garden"**, ask *"What's ready to harvest?"*. Expand the `🔄 Plan → Act → Observe → Adapt` badge → open the full trace. In another terminal: `docker compose logs -f vgarden` shows the loop phases live. |
| ~3 min | **Amy — Plant Almanac** (`/almanac/`) | Browse the 16 seeded plants. **CRUD**: *+ Add a plant* (name + planting-month toggles) → open it → *Edit* → *Delete this plant*. Show `GET /almanac/api/plants` JSON. Open **"Ask the Almanac"**, ask *"What can I plant in April?"* → grounded answer + source links + loop badge. |
| ~3 min | **Guhan — Plant Health** (`/health/plant-health-records/`) | New assessment: type a description (and/or upload a photo) → watch it **stream in**. Open a seeded record → **"Discuss this assessment"**, ask *"Why do you think that?"* → loop badge + trace. **CRUD**: *Edit details* (plant name / notes) → Save; *Delete this record*. Show `GET .../assessments` JSON. |
| 9:30 | any | Recap: one origin on `:3000`, three LLM-backed features each running Plan → Act → Observe → Adapt, CI green, evidence in `tools/ai-loop/logs/`. |

## 7. Evidence to capture for the report (§11 / §12)

```bash
docker compose ps                                        # -> screenshot
curl -fs http://127.0.0.1:3000/                           # frontend
curl -fs http://127.0.0.1:3000/auth/login
curl -fs http://127.0.0.1:3000/vgarden/healthz            # {"status":"ok",...}
curl -fs http://127.0.0.1:3000/almanac/health
python tools/ai-loop/view.py                              # recent loop runs
python tools/ai-loop/view.py <run_id>                     # one full trace
```

Plus: the GitHub Actions runs for `vgarden.yml`, `auth.yml`, `almanac.yml`,
`health.yml`, and `integration-ci.yml` after pushing the branch.

## 8. If something misbehaves

| Symptom | Fix |
|---|---|
| A feature shows no seed data | You forgot `docker compose down -v`. Reset. |
| "local AI model is unavailable" | `docker compose exec ollama ollama list` — pull the missing model; check `docker compose logs ollama`. |
| First answer takes minutes | Model wasn't pre-warmed (step 4) or you're on CPU. |
| Reviewer loops forever | It won't — it caps at `AI_LOOP_MAX_ITERATIONS=2` and returns `revised_capped`. |
| Login says "session expired" after visiting a garden | Different browser/incognito; log in again. Auth and vgarden use separate cookies. |

# Plant Almanac microservice

The Plant Almanac is a Flask, Jinja, HTMX, Alpine.js, and SQLite service that owns
general plant reference data. It is available at <http://localhost:3000/almanac/>
through the shared nginx proxy.

## What it currently does

* Displays eight seeded plant references and their planting months.
* Full CRUD on plant references (browser forms + JSON API), gated by Auth login.
* Accepts JPEG, PNG, GIF, and WebP plant images by choosing, dropping, or pasting a
  file. Large browser uploads are compressed automatically before submission.
* Provides public read JSON APIs for other services.
* Provides a floating **Ask the Almanac** chat powered by local Ollama.
* Grounds AI answers in Almanac records and displays the records used as sources.
* Runs answers through Plan → Act → Observe → Adapt validation and opens the process
  summary in a report popup.
* Saves recent chat history under the authenticated Auth user ID and uses it as
  conversational context.
* Keeps the AI read-only: it cannot modify plant or project data.

Plant pages and read APIs are public. Login is required for plant changes, AI chat,
and chat history.

## Run locally

Run commands from the repository root:

```bash
docker compose up -d --build proxy auth ollama almanac
docker compose exec ollama ollama pull qwen3:4b-instruct  # first run only
```

Then:

1. Log in at <http://localhost:3000/auth/login>.
2. Open the Almanac at <http://localhost:3000/almanac/>.
3. Use the floating button to open the chat.

Check the service:

```bash
docker compose ps almanac
docker compose logs -f almanac
curl http://localhost:3000/almanac/health
```

## Service boundaries

| Dependency | How the Almanac uses it |
| --- | --- |
| Auth | Forwards the browser login cookie to Auth's `/me` API; never reads Auth's database |
| Ollama | Sends grounded prompts to `qwen3:4b-instruct` |
| Almanac database | Owns plant references, planting months, image metadata, authenticated chat messages, and validation runs |

Recent saved messages are sent with the current question as conversational context.

## Endpoints

| Endpoint | Purpose | Login required |
| --- | --- | --- |
| `/` | Plant cards and floating chat launcher | No (chat and add require login) |
| `/plants/<slug>` | Plant reference detail | No |
| `/plant-images/<filename>` | Stored plant image | No |
| `/plants/new`, `POST /plants` | Add a plant reference (form) | Yes |
| `/plants/<slug>/edit`, `POST /plants/<slug>/edit` | Edit a plant reference (form) | Yes |
| `POST /plants/<slug>/delete` | Delete a plant reference | Yes |
| `/api/plants` | All plant records as JSON (`GET`); create (`POST`) | Write only |
| `/api/plants/<slug>` | One plant record (`GET`); update (`PUT`/`PATCH`); delete (`DELETE`) | Write only |
| `/ai/ask` | Ask the grounded AI assistant (Plan → Act → Observe → Adapt loop) | Yes |
| `/ai/clear` | Clear the current user's chat (route only; no visible button) | Yes |
| `/ai/loop/<id>` | Validation report for one agentic-loop run | Yes |
| `/health` | Database and service health check | No |

Plant pages are public to read. Any logged-in user can add, edit, or delete plant
references (there is no admin role in Release 0). Browser mutations are CSRF-protected;
the JSON write API is CSRF-exempt and authenticates by forwarding the login cookie to
Auth's `/me`.

## Configuration

| Variable | Purpose | Compose value |
| --- | --- | --- |
| `DATABASE_URL` | Almanac-owned database | `sqlite:////app/instance/almanac.db` |
| `AUTH_URL` | Internal Auth service URL | `http://auth:5000` |
| `AUTH_PUBLIC_URL` | Browser-facing Auth URL | `http://localhost:3000/auth` |
| `OLLAMA_URL` | Internal Ollama API | `http://ollama:11434` |
| `OLLAMA_MODEL` | Chat model | `qwen3:4b-instruct` |
| `OLLAMA_REVIEW_MODEL` | Validation reviewer model | `llama3.1:8b` |
| `AI_LOOP_MAX_ITERATIONS` | Maximum draft/review rounds | `2` |
| `AI_LOOP_LOG_DIR` | Validation log and report directory | `/app/ai_loop_logs` |
| `PLANT_IMAGE_FOLDER` | Stored plant image directory | `/app/instance/plant_images` |
| `OLLAMA_TIMEOUT` | Maximum AI request time | `120` seconds by default |
| `FLASK_DEBUG` | Development reload | `1` |

## Development and tests

The `almanac/` directory is bind-mounted and Flask reload is enabled. Python and template
edits restart the service automatically; refresh the browser to see template changes.
Rebuild only after changing `Dockerfile` or `requirements.txt`.

Run the focused tests inside the container:

```bash
docker compose exec almanac python -m pytest -q
```

The tests use fake Auth and AI clients, so they do not call Ollama or require a real login.

## Persistence

SQLite data and uploaded plant images are stored in the `almanac_data` Docker volume
and survive container restarts. `docker compose down -v` deletes that local data and
those images.

# Plant Almanac microservice

The Plant Almanac is a Flask, Jinja, HTMX, Alpine.js, and SQLite service that owns
general plant reference data. It runs on <http://localhost:5004> through Docker Compose.

## What it currently does

* Displays seeded plant references and planting months.
* Provides public JSON APIs for other services.
* Provides a floating **Ask the Almanac** chat powered by local Ollama.
* Grounds AI answers in Almanac records and displays the records used as sources.
* Saves chat history under the authenticated Auth user ID.
* Keeps the AI read-only: it cannot modify plant or project data.

Plant pages are public. Login is required only for AI chat and chat history.

## Run locally

Run commands from the repository root:

```bash
docker compose up -d auth ollama almanac
docker compose exec ollama ollama pull qwen3:4b-instruct  # first run only
```

Then:

1. Log in at <http://localhost:5001/login>.
2. Open the Almanac at <http://localhost:5004>.
3. Use the floating button to open the chat.

Check the service:

```bash
docker compose ps almanac
docker compose logs -f almanac
curl http://localhost:5004/health
```

## Service boundaries

| Dependency | How the Almanac uses it |
| --- | --- |
| Auth | Forwards the browser login cookie to Auth's `/me` API; never reads Auth's database |
| Ollama | Sends grounded prompts to `qwen3:4b-instruct` |
| Almanac database | Owns plant references, planting months, and authenticated chat messages |

Saved messages are displayed as history, but earlier messages are not currently sent back
to Ollama as conversational context.

## Endpoints

| Endpoint | Purpose | Login required |
| --- | --- | --- |
| `/` | Plant cards and floating chat launcher | Chat only |
| `/plants/<slug>` | Plant reference detail | No |
| `/api/plants` | All plant records as JSON | No |
| `/api/plants/<slug>` | One plant record as JSON | No |
| `/ai/ask` | Ask the grounded AI assistant | Yes |
| `/ai/clear` | Clear the current user's chat | Yes |
| `/health` | Database and service health check | No |

## Configuration

| Variable | Purpose | Compose value |
| --- | --- | --- |
| `DATABASE_URL` | Almanac-owned database | `sqlite:////app/instance/almanac.db` |
| `AUTH_URL` | Internal Auth service URL | `http://auth:5000` |
| `AUTH_PUBLIC_URL` | Browser-facing Auth URL | `http://localhost:5001` |
| `OLLAMA_URL` | Local Ollama API | `http://host.docker.internal:11434` |
| `OLLAMA_MODEL` | Chat model | `qwen3:4b-instruct` |
| `OLLAMA_TIMEOUT` | Maximum AI request time | `120` seconds by default |
| `FLASK_DEBUG` | Development reload | `1` |

## Development and tests

The `almanac/` directory is bind-mounted and Flask reload is enabled. Python and template
edits restart the service automatically; refresh the browser to see template changes.
Rebuild only after changing `Dockerfile` or `requirements.txt`.

Run the focused tests inside the container:

```bash
docker compose exec almanac python -m unittest discover -s tests -v
```

The tests use fake Auth and AI clients, so they do not call Ollama or require a real login.

## Persistence

SQLite data is stored in the `almanac_data` Docker volume and survives container restarts.
`docker compose down -v` deletes that local data.

# Plant Almanac microservice

The Plant Almanac is a Flask, Jinja, HTMX, Alpine.js, and SQLite service that owns
general plant reference data. It is available at <http://localhost:3000/almanac/>
through the shared nginx proxy.

## Release 1 (Amy)

Open **Reference tools** for read-only MCP catalogue search and RAG answers with source links, confidence and insufficient-context handling. Both go through this backend to the group’s shared local servers. See the shared [MCP setup](../ai-services/mcp-server/README.md), [RAG setup](../ai-services/rag-server/README.md), and [validation commands](../tools/ai-loop/README.md#release-1-validate-mcp-and-rag-through-the-feature).

## What it currently does

* Loads plant references and their planting months from the public My Garden catalogue; eight starter plants are a fallback when the source is unavailable.
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
ollama pull qwen3:4b-instruct  # host Ollama, first run only
docker compose up -d --build proxy auth almanac
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

### Import My Garden into an existing database

The public source is [0melette/my_garden](https://github.com/0melette/my_garden).
Startup only seeds an empty database. If this checkout already has the older
starter plants, back up its database and explicitly import missing source data:

```bash
docker compose exec almanac python -m flask --app app import-my-garden
```

This adds missing plants, fills blank fields and adds missing relationships and
images. It preserves existing values, notes and images; running it again does not
duplicate records. It does not publish app edits back to My Garden. After an
import, refresh the shared RAG index with `POST /rag/ingest/almanac`.

## Service boundaries

| Dependency | How the Almanac uses it |
| --- | --- |
| Auth | Forwards the browser login cookie to Auth's `/me` API; never reads Auth's database |
| Ollama | Sends grounded prompts to `qwen3:4b-instruct` |
| Almanac database | Owns plant references, planting months, stored image filenames, authenticated chat messages, and validation runs |

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
| `/ai/clear` | Start a new chat with empty context | Yes |
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
| `OLLAMA_URL` | Host Ollama API | `http://host.docker.internal:11434` |
| `OLLAMA_MODEL` | Chat model | `qwen3:4b-instruct` |
| `OLLAMA_REVIEW_MODEL` | Validation reviewer model | `llama3.1:8b` |
| `AI_LOOP_MAX_ITERATIONS` | Maximum draft/review rounds | `2` |
| `AI_LOOP_LOG_DIR` | Validation log and report directory | `/app/ai_loop_logs` |
| `PLANT_IMAGE_FOLDER` | Stored plant image directory | `/app/instance/plant_images` |
| `MY_GARDEN_IMAGE_BASE_URL` | Public image directory for the starter catalogue | `https://raw.githubusercontent.com/0melette/my_garden/main/localdata/plant_images/` |
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

## Yield planning and growing knowledge

See [PLANNING.md](PLANNING.md) for migrations, public starter data, field explanations, companion suggestions, editing and API usage.

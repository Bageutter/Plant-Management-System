# Shared RAG server

One **local, non-containerised** Retrieval-Augmented Generation server for the whole
Plant Management System. Feature backends (Plant Health first) send it questions from
their own API routes, so the frontend reaches RAG *through* the backend — the Release 1
requirement. It is never a `docker compose` service.

Design, retrieval gate and confidence rules: [`docs/ai/mcp-rag-design.md`](../../docs/ai/mcp-rag-design.md).

```text
feature UI ─► feature backend/API ─► shared RAG server (localhost:5106) ─► SQLite chunk store
                                                        └─► local Ollama (/api/embed, /api/chat)
```

## Status of this branch

The **base structure** is in place and every endpoint exists with its final contract.
Retrieval, grounding and generation, and the health knowledge source, land in the
`claude/health-mcp-rag-integration` branch. Until then:

| Endpoint | Now |
| --- | --- |
| `GET /healthz` | live: Ollama reachability, chunk count, enabled flag |
| `GET /` | live: HTMX page (query form + indexed sources table) |
| `GET /rag/sources` | live: known sources with document/chunk counts |
| `POST /rag/ingest/<source>` | `501` for `health`, `almanac`, `vgarden`; `404` for anything else |
| `POST /rag/query` | validates input (`400`), then `501` — never a fabricated answer |

`RAG_ENABLED=false` (what CI uses) keeps `/healthz` and `/` up and turns every other
endpoint into a `503` with `{"enabled": false}`.

## Run it

From the repository root, in the same virtualenv as the MCP server:

```bash
.venv/Scripts/python -m pip install -r ai-services/rag-server/requirements-dev.txt   # Windows
python ai-services/rag-server/app.py
# -> http://127.0.0.1:5106
```

### Configuration

| Env | Default | Purpose |
| --- | --- | --- |
| `RAG_ENABLED` | `true` | operational switch (CI sets `false`) |
| `RAG_HOST` / `RAG_PORT` | `127.0.0.1` / `5106` | listener; containers use `host.docker.internal:5106` |
| `RAG_DATABASE_PATH` | `ai-services/rag-server/instance/rag.db` | SQLite chunk store |
| `HEALTH_SERVICE_URL` | `http://127.0.0.1:3000/health` | health public API (through the proxy) |
| `ALMANAC_SERVICE_URL`, `VGARDEN_SERVICE_URL` | via the proxy | reserved for the stub sources |
| `OLLAMA_URL` / `OLLAMA_MODEL` | `http://localhost:11434` / `qwen3:4b-instruct` | local answering model |
| `RAG_EMBED_MODEL` | `nomic-embed-text` | local embedding model; empty → lexical retrieval only |
| `RAG_TOP_K` | `5` | passages handed to the model (max 10) |
| `RAG_MIN_COVERAGE` / `RAG_MIN_SIMILARITY` | `0.34` / `0.45` | relevance gate → "insufficient context" |

## Response contract (`POST /rag/query`)

```json
{
  "question": "…",
  "answer": "… or null",
  "confidence": "high | medium | low | insufficient",
  "insufficient_context": false,
  "citations": [{"chunk_id": "health:12:summary", "source": "health", "source_id": "12",
                 "title": "Assessment #12 — Tomato, back bed", "url": "…", "excerpt": "…", "score": 0.71}],
  "retrieval": {"mode": "lexical | hybrid", "candidates": 9, "top_k": 5},
  "model": "qwen3:4b-instruct",
  "duration_ms": 4120
}
```

## Tests

```bash
cd ai-services/rag-server
python -m pytest -q
```

No Ollama and no feature service are needed.

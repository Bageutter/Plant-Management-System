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

## Endpoints

| Endpoint | Behaviour |
| --- | --- |
| `GET /healthz` | Ollama reachability (503 = degraded), chunk count, enabled flag |
| `GET /` | HTMX page: query form + indexed sources table |
| `GET /rag/sources` | known sources with `implemented`, document and chunk counts |
| `POST /rag/ingest/health` | **implemented**: pages `GET /plant-health-records/assessments` from the health API and indexes summary / description / issues / recommendations / missing-information passages per record (embeddings best-effort). Idempotent; deleted records disappear. |
| `POST /rag/ingest/almanac`, `.../vgarden` | `501` stubs — issues #43, #44 |
| `POST /rag/query` | `400` on bad input; otherwise the grounded-answer contract below. Nothing relevant retrieved → `insufficient_context: true` **without a model call**. |

### How an answer is produced

1. **Retrieve** — BM25 over every indexed passage (title + text), plus cosine similarity
   when both the query and the passages have embeddings (`retrieval.mode = "hybrid"`).
2. **Gate** — a passage counts as relevant only if it covers ≥ `RAG_MIN_COVERAGE` of the
   question's terms or its similarity ≥ `RAG_MIN_SIMILARITY`. Nothing passes → refusal.
3. **Ground + generate** — the top-k passages become the *only* facts in the prompt;
   local Ollama answers at `temperature 0` against a pinned JSON schema
   (`answer`, `cited_chunk_ids`, `evidence_strength`, `insufficient_context`).
4. **Re-validate** — citations the model did not receive are dropped; its
   `insufficient_context` flag is honoured; an answer with no valid citation is pinned to
   the top passage and capped at `low`.
5. **Confidence category** (in code): `high` = ≥ 2 citations, top relevance ≥ 0.6 and
   `strong`; `low` = `weak`, or a single weak citation, or the no-citation fallback;
   `medium` otherwise; `insufficient` when refused. The response also carries
   `model_confidence` — the model's own `evidence_strength` rating (`null` when the gate
   refused before the model was called) — and `confidence_reason`, a plain-words
   justification built from the same inputs, so callers can show *why* a category was
   chosen and how the model's self-assessment fed into it.

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
  "confidence_reason": "2 cited passages, top relevance 84%; model rated its evidence strong, meeting every high-confidence rule.",
  "model_confidence": "weak | moderate | strong | null",
  "insufficient_context": false,
  "citations": [{"chunk_id": "health:12:summary", "source": "health", "source_id": "12",
                 "title": "Assessment #12 — Tomato, back bed", "url": "…",
                 "recorded_at": "2026-09-20T05:30:00+00:00", "excerpt": "…", "score": 0.71}],
  "retrieval": {"mode": "lexical | hybrid", "candidates": 2, "considered": 9, "top_k": 5,
                "query_terms": ["tomato", "yellow"], "sources": ["health"]},
  "model": "qwen3:4b-instruct or null",
  "duration_ms": 4120,
  "note": "… or null"
}
```

`model` is `null` only when the model was not consulted (relevance gate refusal).
`model_confidence` is `null` when the model was not consulted or did not supply a valid
rating; it is never filled in by code.

## Tests

```bash
cd ai-services/rag-server
python -m pytest -q
```

No Ollama and no feature service are needed: retrieval and the confidence rules are
tested directly, generation is faked, and the health source is ingested from a fake
health API on a real socket (paging, deletions, outages).

# ChromaDB: how this version works

The plant, health and garden databases remain the originals. ChromaDB is an extra,
rebuildable search copy: passage text, source links and Ollama embedding vectors.
It runs inside the local Python RAG process and persists in `instance/chroma`.
No external AI provider receives the records.

## Start

Install `ai-services/rag-server/requirements.txt` in the existing Python environment.
The tested embedding model is `bge-m3:latest`, already installed in local Ollama.

```sh
export PYTHONDONTWRITEBYTECODE=1
export RAG_BACKEND=chroma
export RAG_EMBED_MODEL=bge-m3:latest
export OLLAMA_AUTO_PULL=false
python ai-services/rag-server/app.py
```

Then refresh each source (feature services must be running):

```sh
curl -X POST http://127.0.0.1:5106/rag/ingest/almanac
curl -X POST http://127.0.0.1:5106/rag/ingest/health
curl -X POST http://127.0.0.1:5106/rag/ingest/vgarden
```

The same `/rag/query` interface serves all three features. Chroma finds nearby
vectors, then the existing relevance checks and answer/citation logic apply.
Date and exact-record comparison shortcuts remain deterministic.
`POST /rag/retrieve` returns passages without generating an answer.
Chroma failure does not silently pretend to be vector search.

## MCP

Start `python ai-services/mcp-server/server.py` in its existing environment.
The three added tools are:

| Tool | Purpose |
| --- | --- |
| `retrieve_context` | Return relevant passages, IDs, links and ranking scores. |
| `answer_question` | Return a grounded answer, citations and evidence category. |
| `refresh_corpus` | Rebuild a derived index; requires `MCP_RAG_REFRESH_ENABLED=true`. |

Inputs are bounded and sources fixed. These tools expose Almanac and Health;
private garden RAG stays in the authenticated application path. MCP is a trusted
local operator service, not a public multi-user API. Garden source IDs are filtered
inside Chroma before nearest-neighbour selection; this is isolation, not a replacement
for the application's owner permission check. Existing direct RAG HTTP endpoints
remain trusted-local interfaces and must not be exposed publicly.

## Refresh and rollback

Every refresh builds a new collection. Only after all passages and embeddings
are stored does an atomic manifest replacement activate it. Missing/invalid
embeddings fail refresh without replacing the active index. Deleted records
vanish from the active collection on refresh. Old collections remain for recovery.
Run only one RAG writer process per Chroma directory.

Back up `instance/chroma/active.json` before a refresh. Stop the service and restore
that manifest to reactivate the retained collections. Changing embedding model
requires a new `RAG_CHROMA_PATH` and a full refresh. Keep model versions stable.
For the old lexical baseline, run `RAG_BACKEND=sqlite RAG_EMBED_MODEL=''`;
its original `rag.db` has not been migrated or deleted.

## Measure it

```sh
RAG_EMBED_MODEL=bge-m3:latest python ai-services/rag-server/evaluate.py --output /tmp/rag-results.json
```

This compares lexical and vector top-five results on exactly the same passages.
The output includes corpus, evaluator and label hashes, index timestamps, the Git
commit and dirty state. The expanded benchmark has 30 positive questions across
all three features and 6 off-topic controls. Both methods achieved Recall@5 1.00
and Precision@5 0.22; Chroma did not outperform lexical search. Labels still need
human review. See [dated results and limitations](evidence/benchmark-2026-10-04.md).

Still separate work: broader benchmark labels, claim-by-claim evidence validation,
and generic plant-name comparison (e.g. cucumber mapping to multiple varieties).
Chroma alone does not fix those application behaviours.

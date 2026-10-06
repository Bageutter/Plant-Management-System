# Chroma retrieval benchmark — 4 October 2026

## Scope and method

Local branch `amy/chromadb`, uncommitted working tree. This evaluates retrieval,
not deployment, browser interactions, answer factuality or the whole Release 1.
The existing 2 October index was read without refreshing production data:
44 Almanac passages, 6 Health passages, 8 Virtual Garden passages (58 total).
Both methods used the same source-scoped records. Garden queries additionally
filtered by source_id before ranking. No private garden text is reproduced here.

The query set now contains 30 answerable retrieval tasks (18 Almanac, 6 Health,
6 Virtual Garden) and 6 off-topic controls. It covers names, paraphrases, a typo,
comparisons, explicitly missing information and garden-scoped lookups.
Labels were authored by the assistant from the indexed records before running
retrieval. They remain provisional until a person reviews relevance judgments.
This is a small, corpus-informed exploratory benchmark, not a held-out study.

Baseline: the application's lexical BM25/term-coverage retriever, including its
name correction and named-guide rules. Comparator: Chroma cosine top-five search
using local Ollama bge-m3:latest, 1,024-dimensional embeddings. Both also undergo
the application's relevance gate/reranker: coverage 0.34 or cosine similarity 0.45.
No answer model is invoked. Deterministic date/comparison shortcuts are not run.

## Results

| Measure | Lexical | Chroma |
| --- | ---: | ---: |
| Macro Precision@5 | 0.220 | 0.220 |
| Macro Recall@5 | 1.000 | 1.000 |
| Mean reciprocal rank | 0.933 | 0.908 |
| Recall@5 after relevance filtering | 1.000 | 1.000 |
| Off-topic queries rejected after filtering | 6/6 | 6/6 |
| Source/scope violations in retrieved results | 0 | 0 |

Precision divides relevant hits by five even when fewer than five are returned.
With mostly one relevant passage per question, 0.20 can mean the expected passage
was found. Recall divides hits by the number of labelled relevant passages.
Negative controls are excluded from precision/recall and scored separately.
Mean reciprocal rank measures where the first labelled relevant passage appears.
Chroma returned all labelled passages but ranked the first relevant result slightly
lower overall. There is no demonstrated quality advantage on this sample.
Small Health/garden corpora make Recall@5 relatively easy. More diverse, independent
questions and human-reviewed labels are required before generalising.

## Reproduce and inspect

From the repository root, with dependencies installed in a Python environment:

```sh
RAG_EMBED_MODEL=bge-m3:latest OLLAMA_AUTO_PULL=false \
  ai-services/rag-server/.venv/bin/python ai-services/rag-server/evaluate.py \
  --output docs/ai/evidence/chroma-benchmark-2026-10-04.json
ai-services/rag-server/.venv/bin/python -m pytest ai-services/rag-server/tests -q
```

Measured test result: **68 passed**. No mocks were used for the
benchmark's Ollama embeddings or Chroma queries. The separate pytest suite includes
fakes; it must not be presented as live UI validation.
The JSON records per-query expected/retrieved/gated IDs, metrics, source scopes,
index timestamps, model, thresholds, base commit, dirty state, evaluator hash,
label hash and corpus hash (including embeddings). Per-query times are diagnostic
only: one run, no warm-up control, and vector timings include embedding calls.

## Release 1 evidence still required

- Human review of benchmark labels; explicit claim-by-claim review of generated
  answers and cited support. A cited ID alone does not prove a claim is supported.
- Fresh UI + backend MCP and RAG evidence for every feature, including confidence
  categories and insufficient-context responses. This benchmark bypasses HTTP/UI.
- Fresh shared agentic-loop MCP and RAG transcripts; these are distinct from
  this retrieval benchmark and from the unit tests.
- Resolve the current `docker-compose.yml` Ollama service against the brief's
  non-containerised AI-Mode requirement. MCP/RAG themselves run locally.
- Confirm assigned workflow names/CI logs, disabled integration configuration,
  integrated Compose runtime, contribution commits and accessible video/evidence.
- RAG port 5106 was unreachable at the start of this work. Running the offline
  benchmark does not establish that the shared HTTP service is operational.
- Chroma work is local/uncommitted. Do not describe it as merged or deployed.

The Google report is capped at 3,000 words. Keep the result summary there and
retain this detailed evidence alongside the implementation, then commit/push only
when authorised. The historical lexical-only statement requires qualification:
SQLite remains the default; Chroma is selected explicitly with RAG_BACKEND=chroma.

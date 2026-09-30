"""Retrieve → gate → ground → answer → categorise.

This module owns the response contract every feature frontend renders:

    {
      "question": str,
      "answer": str | None,
      "confidence": "high" | "medium" | "low" | "insufficient",
      "insufficient_context": bool,
      "citations": [ {chunk_id, source, source_id, title, url, excerpt, score} ],
      "retrieval": {"mode": "lexical" | "hybrid", "candidates": int, "top_k": int,
                    "considered": int, "query_terms": [...]},
      "model": str | None,
      "duration_ms": int,
      "note": str | None
    }

Refuse-don't-guess is enforced in three places: the relevance gate (nothing
relevant retrieved → no model call at all), the model's own
``insufficient_context`` flag, and the code that drops citations the model did
not actually receive.
"""

from __future__ import annotations

import logging
import time

from embeddings import EmbeddingUnavailable, build_embedder
from generation import ModelUnavailable, build_answerer
from retrieval import Candidate, retrieve

logger = logging.getLogger(__name__)

EXCERPT_CHARS = 240
HIGH_MIN_SCORE = 0.6
LOW_MAX_SCORE = 0.5

__all__ = ["ModelUnavailable", "answer", "categorise", "insufficient"]


def insufficient(question: str, *, retrieval: dict, duration_ms: int = 0, note: str | None = None) -> dict:
    """The fixed refusal payload used whenever nothing relevant was retrieved."""

    return {
        "question": question,
        "answer": None,
        "confidence": "insufficient",
        "insufficient_context": True,
        "citations": [],
        "retrieval": retrieval,
        "model": None,
        "duration_ms": duration_ms,
        "note": note
        or "No indexed passage was relevant enough to this question, so no answer was generated.",
    }


def categorise(cited: list[Candidate], evidence_strength: str, *, fallback: bool) -> str:
    """Confidence category from measurable retrieval evidence plus the model's
    self-reported strength. Documented in docs/ai/mcp-rag-design.md §3."""

    if not cited:
        return "insufficient"
    top = max(c.score for c in cited)
    if fallback or evidence_strength == "weak" or (len(cited) == 1 and top < LOW_MAX_SCORE):
        return "low"
    if len(cited) >= 2 and top >= HIGH_MIN_SCORE and evidence_strength == "strong":
        return "high"
    return "medium"


def answer(
    question: str,
    *,
    sources: tuple[str, ...],
    top_k: int,
    config,
    store,
    embedder=None,
    answerer=None,
) -> dict:
    started = time.monotonic()
    chunks = store.chunks(sources)

    # -- retrieve (dense is best-effort; lexical always works) ----------------
    query_embedding = None
    note = None
    embedder = embedder if embedder is not None else build_embedder(config)
    if embedder is not None and any(c.embedding for c in chunks):
        try:
            query_embedding = embedder.embed([question])[0]
        except EmbeddingUnavailable as exc:
            logger.warning("dense retrieval unavailable, using lexical only: %s", exc)
            note = "Embedding model unavailable; retrieval was lexical only."

    result = retrieve(
        question,
        chunks,
        top_k=top_k,
        min_coverage=config["RAG_MIN_COVERAGE"],
        min_similarity=config["RAG_MIN_SIMILARITY"],
        query_embedding=query_embedding,
    )
    retrieval = {
        "mode": result.mode,
        "candidates": len(result.candidates),
        "considered": result.considered,
        "top_k": top_k,
        "query_terms": result.query_terms,
        "sources": list(sources),
    }
    if not result.candidates:
        return insufficient(question, retrieval=retrieval, duration_ms=_ms(started), note=note)

    # -- ground + generate -------------------------------------------------------
    grounding = {
        "question": question,
        "passages": [
            {
                "chunk_id": c.chunk.chunk_id,
                "source": c.chunk.source,
                "title": c.chunk.title,
                "recorded_at": c.chunk.recorded_at,
                "text": c.chunk.text,
            }
            for c in result.candidates
        ],
    }
    answerer = answerer if answerer is not None else build_answerer(config)
    generated = answerer.generate(question, grounding)

    if generated["insufficient_context"] or not generated["answer"]:
        return insufficient(
            question,
            retrieval=retrieval,
            duration_ms=_ms(started),
            note="The retrieved passages did not contain enough to answer this question.",
        )

    # -- re-validate citations in code -------------------------------------------
    by_id = {c.chunk.chunk_id: c for c in result.candidates}
    cited = [by_id[i] for i in dict.fromkeys(generated["cited_chunk_ids"]) if i in by_id]
    fallback = False
    if not cited:
        # The model answered but cited nothing it was given. Keep the answer
        # traceable to the best passage and cap confidence at "low".
        cited = [result.candidates[0]]
        fallback = True
        note = (note + " " if note else "") + (
            "The model did not cite a passage; the top retrieved passage is shown and "
            "confidence is capped at low."
        )

    text = generated["answer"][: config.get("RAG_MAX_ANSWER_CHARS", 2000)]
    return {
        "question": question,
        "answer": text,
        "confidence": categorise(cited, generated["evidence_strength"], fallback=fallback),
        "insufficient_context": False,
        "citations": [_citation(c) for c in cited],
        "retrieval": retrieval,
        "model": answerer.model,
        "duration_ms": _ms(started),
        "note": note,
    }


def _citation(candidate: Candidate) -> dict:
    chunk = candidate.chunk
    excerpt = chunk.text if len(chunk.text) <= EXCERPT_CHARS else chunk.text[: EXCERPT_CHARS - 1] + "…"
    return {
        "chunk_id": chunk.chunk_id,
        "source": chunk.source,
        "source_id": chunk.source_id,
        "title": chunk.title,
        "url": chunk.url,
        "recorded_at": chunk.recorded_at,
        "excerpt": excerpt,
        "score": candidate.score,
    }


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)

"""Retrieve → gate → ground → answer → categorise.

This module owns the response contract every feature frontend renders:

    {
      "question": str,
      "answer": str | None,
      "confidence": "high" | "medium" | "low" | "insufficient",
      "confidence_reason": str,                       # why that category, in plain words
      "model_confidence": "weak" | "moderate" | "strong" | null,   # the model's own rating
      "insufficient_context": bool,
      "citations": [ {chunk_id, source, source_id, title, url, recorded_at, excerpt, score} ],
      "retrieval": {"mode": "lexical" | "hybrid", "candidates": int, "top_k": int,
                    "considered": int, "query_terms": [...], "sources": [...]},
      "model": str | None,                            # null when the model was not consulted
      "duration_ms": int,
      "note": str | None
    }

Refuse-don't-guess is enforced in three places: the relevance gate (nothing
relevant retrieved → no model call at all), the model's own
``insufficient_context`` flag, and the code that drops citations the model did
not actually receive.

``model_confidence`` is the model's self-reported ``evidence_strength``. It is one
input to the ``confidence`` category, which is otherwise derived from measurable
retrieval evidence (``categorise``); ``confidence_reason`` is built from the same
inputs (``explain``) so the category and its justification can never disagree. The
model's rating is reported as given — ``null`` when the model was not consulted or
did not supply one — never invented.
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

__all__ = ["ModelUnavailable", "answer", "categorise", "explain", "insufficient"]


def insufficient(
    question: str,
    *,
    retrieval: dict,
    duration_ms: int = 0,
    note: str | None = None,
    model: str | None = None,
    model_confidence: str | None = None,
    reason: str | None = None,
) -> dict:
    """The fixed refusal payload used whenever no grounded answer can be given.

    ``model`` and ``model_confidence`` are None when the relevance gate refused before
    the model was consulted; when the model itself declared the passages insufficient
    they carry the model's name and its own evidence rating.
    """

    if reason is None:
        if model is None:
            reason = (
                "No indexed passage passed the relevance gate, so the model was not consulted."
            )
        else:
            reason = "The model judged the retrieved passages insufficient to answer this question"
            reason += (
                f" (its own evidence rating: {model_confidence})." if model_confidence else "."
            )
    return {
        "question": question,
        "answer": None,
        "confidence": "insufficient",
        "confidence_reason": reason,
        "model_confidence": model_confidence,
        "insufficient_context": True,
        "citations": [],
        "retrieval": retrieval,
        "model": model,
        "duration_ms": duration_ms,
        "note": note
        or "No indexed passage was relevant enough to this question, so no answer was generated.",
    }


def categorise(cited: list[Candidate], evidence_strength: str | None, *, fallback: bool) -> str:
    """Confidence category from measurable retrieval evidence plus the model's
    self-reported strength (a missing rating counts as weak). Documented in
    docs/ai/mcp-rag-design.md §3."""

    if not cited:
        return "insufficient"
    strength = evidence_strength or "weak"
    top = max(c.score for c in cited)
    if fallback or strength == "weak" or (len(cited) == 1 and top < LOW_MAX_SCORE):
        return "low"
    if len(cited) >= 2 and top >= HIGH_MIN_SCORE and strength == "strong":
        return "high"
    return "medium"


def explain(cited: list[Candidate], evidence_strength: str | None, *, fallback: bool) -> str:
    """Plain-words justification of the confidence category.

    Derives the category with ``categorise`` from the same inputs, so the reason
    always describes the rule that actually fired.
    """

    if not cited:
        return "No passage was cited."
    category = categorise(cited, evidence_strength, fallback=fallback)
    top = max(c.score for c in cited)
    count = len(cited)
    rating = (
        f"model rated its evidence {evidence_strength}"
        if evidence_strength
        else "model gave no evidence rating (treated as weak)"
    )
    text = f"{count} cited passage{'s' if count != 1 else ''}, top relevance {top:.0%}; {rating}"

    if fallback:
        text += ", but cited none of the passages it was given, so confidence is capped at low"
    elif category == "high":
        text += ", meeting every high-confidence rule"
    elif category == "low":
        if (evidence_strength or "weak") == "weak":
            text += ", which caps confidence at low"
        else:
            text += ", but a single weakly relevant passage caps confidence at low"
    else:  # medium: name the high-confidence rule(s) that were not met
        unmet = []
        if count < 2:
            unmet.append("only one passage was cited")
        if top < HIGH_MIN_SCORE:
            unmet.append(f"top relevance is below {HIGH_MIN_SCORE:.0%}")
        if evidence_strength != "strong":
            unmet.append("the model did not rate its evidence strong")
        text += ", but " + " and ".join(unmet) + ", so confidence stays at medium"
    return text + "."


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
    strength = generated["evidence_strength"]  # None when the model did not report one

    if generated["insufficient_context"] or not generated["answer"]:
        reason = None
        if not generated["insufficient_context"]:
            # The model did not claim insufficiency; it simply produced no answer.
            reason = "The model returned no grounded answer from the retrieved passages"
            reason += f" (its own evidence rating: {strength})." if strength else "."
        return insufficient(
            question,
            retrieval=retrieval,
            duration_ms=_ms(started),
            note="The retrieved passages did not contain enough to answer this question.",
            model=answerer.model,
            model_confidence=strength,
            reason=reason,
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
        "confidence": categorise(cited, strength, fallback=fallback),
        "confidence_reason": explain(cited, strength, fallback=fallback),
        "model_confidence": strength,
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

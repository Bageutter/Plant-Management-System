"""Retrieve → gate → ground → answer.

This module owns the response contract every feature frontend renders:

    {
      "question": str,
      "answer": str | None,
      "confidence": "high" | "medium" | "low" | "insufficient",
      "insufficient_context": bool,
      "citations": [ {chunk_id, source, source_id, title, url, excerpt, score} ],
      "retrieval": {"mode": "lexical" | "hybrid", "candidates": int, "top_k": int},
      "model": str | None,
      "duration_ms": int
    }

The retrieval, grounding and generation steps land in the
claude/health-mcp-rag-integration branch; this branch pins the contract and
returns an explicit not-implemented error so nothing is ever guessed.
"""

from __future__ import annotations

TRACKING = "docs/ai/mcp-rag-design.md section 3 (branch claude/health-mcp-rag-integration)"


class PipelineNotImplemented(NotImplementedError):
    def __init__(self):
        super().__init__(
            "Grounded answering is not implemented in the shared RAG server yet; "
            f"tracked in {TRACKING}. No answer was generated."
        )


class ModelUnavailable(RuntimeError):
    """Local Ollama could not be reached or did not return a usable answer."""


def insufficient(question: str, *, retrieval: dict, duration_ms: int = 0) -> dict:
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
    }


def answer(question: str, *, sources: tuple[str, ...], top_k: int, config, store) -> dict:
    raise PipelineNotImplemented()

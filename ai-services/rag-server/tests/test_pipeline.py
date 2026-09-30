"""Grounded-answer pipeline with a fake answerer: refusal paths, citation
re-validation and the confidence rules. No Ollama involved."""

from __future__ import annotations

import os

import pytest

import pipeline
from app import create_app
from generation import ModelUnavailable, parse_generation
from store import Chunk, ChunkStore
from tests.test_retrieval import CHUNKS

CONFIG = {"RAG_MIN_COVERAGE": 0.34, "RAG_MIN_SIMILARITY": 0.45, "RAG_MAX_ANSWER_CHARS": 2000}


class FakeAnswerer:
    model = "fake-model"

    def __init__(self, reply):
        self.reply = reply
        self.groundings = []

    def generate(self, question, grounding):
        self.groundings.append(grounding)
        if isinstance(self.reply, Exception):
            raise self.reply
        return dict(self.reply)


@pytest.fixture
def store(tmp_path):
    s = ChunkStore(os.path.join(tmp_path, "s.db"))
    s.replace_source("health", CHUNKS, documents=2)
    yield s
    s.close()


def ask(store, question, answerer, **overrides):
    return pipeline.answer(
        question,
        sources=("health",),
        top_k=overrides.pop("top_k", 5),
        config={**CONFIG, **overrides},
        store=store,
        embedder=None if "embedder" not in overrides else overrides["embedder"],
        answerer=answerer,
    )


def test_off_topic_question_is_refused_before_any_model_call(store):
    answerer = FakeAnswerer({"answer": "should not be used"})
    result = ask(store, "What is the capital of France?", answerer)
    assert result["insufficient_context"] is True and result["confidence"] == "insufficient"
    assert result["answer"] is None and result["citations"] == []
    assert result["retrieval"]["candidates"] == 0 and result["retrieval"]["considered"] == 3
    assert answerer.groundings == []  # the model was never consulted


def test_grounded_answer_carries_only_real_citations_and_high_confidence(store):
    answerer = FakeAnswerer(
        {
            "answer": "Assessment #3 found the tomato at risk from overwatering and advised watering less.",
            "cited_chunk_ids": ["health:3:summary", "health:3:recommendations", "health:999:made-up"],
            "evidence_strength": "strong",
            "insufficient_context": False,
        }
    )
    result = ask(store, "What is wrong with the tomato in the back bed and what should I do?", answerer)
    assert result["insufficient_context"] is False
    assert [c["chunk_id"] for c in result["citations"]] == ["health:3:summary", "health:3:recommendations"]
    assert result["confidence"] == "high"
    assert result["model"] == "fake-model" and result["retrieval"]["mode"] == "lexical"
    citation = result["citations"][0]
    assert citation["title"].startswith("Assessment #3") and citation["source_id"] == "3"
    assert 0 < citation["score"] <= 1

    # The grounding handed to the model is exactly the retrieved passages, nothing else.
    passages = answerer.groundings[0]["passages"]
    assert {p["chunk_id"] for p in passages} <= {c.chunk_id for c in CHUNKS}
    assert all(set(p) == {"chunk_id", "source", "title", "recorded_at", "text"} for p in passages)


def test_model_insufficient_flag_is_honoured(store):
    answerer = FakeAnswerer(
        {"answer": "", "cited_chunk_ids": [], "evidence_strength": "weak", "insufficient_context": True}
    )
    # Passes the retrieval gate (the tomato passages match) but the passages cannot answer it.
    result = ask(store, "Was the tomato fertilised?", answerer)
    assert result["insufficient_context"] is True and result["confidence"] == "insufficient"
    assert result["answer"] is None
    assert "did not contain enough" in result["note"]


def test_uncited_answer_falls_back_to_top_passage_with_low_confidence(store):
    answerer = FakeAnswerer(
        {
            "answer": "The tomato was overwatered.",
            "cited_chunk_ids": [],
            "evidence_strength": "strong",
            "insufficient_context": False,
        }
    )
    result = ask(store, "Why is the tomato yellow?", answerer)
    assert result["confidence"] == "low"
    assert [c["chunk_id"] for c in result["citations"]] == ["health:3:summary"]
    assert "capped at low" in result["note"]


def test_confidence_rules():
    high = [_cand(0.9), _cand(0.7)]
    assert pipeline.categorise(high, "strong", fallback=False) == "high"
    assert pipeline.categorise(high, "moderate", fallback=False) == "medium"
    assert pipeline.categorise(high, "weak", fallback=False) == "low"
    assert pipeline.categorise([_cand(0.9)], "strong", fallback=False) == "medium"  # one passage only
    assert pipeline.categorise([_cand(0.3)], "strong", fallback=False) == "low"  # weak relevance
    assert pipeline.categorise(high, "strong", fallback=True) == "low"
    assert pipeline.categorise([], "strong", fallback=False) == "insufficient"


def test_model_outage_propagates_as_503_through_the_api(tmp_path, monkeypatch):
    monkeypatch.setattr("routes._ollama_reachable", lambda: False)
    app = create_app(
        {"TESTING": True, "RAG_ENABLED": True, "RAG_DATABASE_PATH": os.path.join(tmp_path, "a.db")}
    )
    app.extensions["chunk_store"].replace_source("health", CHUNKS, documents=2)
    monkeypatch.setattr(
        "pipeline.build_answerer", lambda config: FakeAnswerer(ModelUnavailable("Ollama is down."))
    )
    monkeypatch.setattr("pipeline.build_embedder", lambda config: None)
    client = app.test_client()

    response = client.post("/rag/query", json={"question": "Why is the tomato yellow?"})
    assert response.status_code == 503 and "Ollama is down" in response.get_json()["error"]

    # Off-topic questions never reach the model, so they succeed even during an outage.
    response = client.post("/rag/query", json={"question": "capital of France"})
    assert response.status_code == 200 and response.get_json()["confidence"] == "insufficient"

    # And the HTMX fragment renders the insufficient state.
    response = client.post(
        "/rag/query", data={"question": "capital of France"}, headers={"HX-Request": "true"}
    )
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'data-confidence="insufficient"' in html and "Not enough relevant context" in html
    app.extensions["chunk_store"].close()


def test_parse_generation_is_defensive():
    parsed = parse_generation('{"answer": " x ", "cited_chunk_ids": ["a", 1, ""], "evidence_strength": "STRONG"}')
    assert parsed == {
        "answer": "x",
        "cited_chunk_ids": ["a", "1"],
        "evidence_strength": "strong",
        "insufficient_context": False,
    }
    assert parse_generation("{}")["evidence_strength"] == "weak"
    with pytest.raises(ModelUnavailable):
        parse_generation("not json")
    with pytest.raises(ModelUnavailable):
        parse_generation("[1, 2]")


def _cand(score):
    from retrieval import Candidate

    return Candidate(Chunk("health", "1", "p", "t", "x"), 1.0, 1.0, None, score)

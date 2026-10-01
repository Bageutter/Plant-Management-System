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
    assert result["model_confidence"] is None
    assert "model was not consulted" in result["confidence_reason"]


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
    assert result["model_confidence"] == "strong"
    reason = result["confidence_reason"]
    assert reason.startswith("2 cited passages, top relevance ") and "model rated its evidence strong" in reason
    assert "high-confidence" in reason
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
    # The model was consulted and declared the passages insufficient: its rating and
    # name are kept so the UI can attribute the refusal correctly.
    assert result["model_confidence"] == "weak" and result["model"] == "fake-model"
    assert "judged the retrieved passages insufficient" in result["confidence_reason"]


def test_empty_answer_without_the_flag_is_refused_with_an_honest_reason(store):
    answerer = FakeAnswerer(
        {"answer": "", "cited_chunk_ids": [], "evidence_strength": "strong", "insufficient_context": False}
    )
    result = ask(store, "Why is the tomato yellow?", answerer)
    assert result["insufficient_context"] is True and result["model"] == "fake-model"
    assert result["model_confidence"] == "strong"
    assert result["confidence_reason"].startswith("The model returned no grounded answer")
    assert "judged" not in result["confidence_reason"]


def test_missing_model_rating_is_treated_as_weak_but_not_attributed(store):
    answerer = FakeAnswerer(
        {
            "answer": "The tomato was overwatered.",
            "cited_chunk_ids": ["health:3:summary", "health:3:recommendations"],
            "evidence_strength": None,
            "insufficient_context": False,
        }
    )
    result = ask(store, "Why is the tomato in the back bed yellow?", answerer)
    assert result["confidence"] == "low" and result["model_confidence"] is None
    assert "gave no evidence rating (treated as weak)" in result["confidence_reason"]


def test_model_declared_refusal_renders_its_rating_in_the_fragment(tmp_path, monkeypatch):
    monkeypatch.setattr("routes._ollama_reachable", lambda: True)
    app = create_app(
        {"TESTING": True, "RAG_ENABLED": True, "RAG_DATABASE_PATH": os.path.join(tmp_path, "m.db")}
    )
    app.extensions["chunk_store"].replace_source("health", CHUNKS, documents=2)
    monkeypatch.setattr(
        "pipeline.build_answerer",
        lambda config: FakeAnswerer(
            {"answer": "", "cited_chunk_ids": [], "evidence_strength": "weak", "insufficient_context": True}
        ),
    )
    monkeypatch.setattr("pipeline.build_embedder", lambda config: None)
    response = app.test_client().post(
        "/rag/query", data={"question": "Was the tomato fertilised?"}, headers={"HX-Request": "true"}
    )
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'data-confidence="insufficient"' in html and 'data-model-confidence="weak"' in html
    assert "Why insufficient context:" in html and "judged the retrieved passages insufficient" in html
    app.extensions["chunk_store"].close()


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
    assert result["model_confidence"] == "strong"  # the model's rating is reported unchanged
    assert "cited none of the passages" in result["confidence_reason"]


def test_confidence_reason_matches_the_category_rules():
    high = [_cand(0.9), _cand(0.7)]
    assert pipeline.explain(high, "strong", fallback=False) == (
        "2 cited passages, top relevance 90%; model rated its evidence strong, "
        "meeting every high-confidence rule."
    )
    # medium names every unmet high-confidence rule
    assert pipeline.explain(high, "moderate", fallback=False) == (
        "2 cited passages, top relevance 90%; model rated its evidence moderate, "
        "but the model did not rate its evidence strong, so confidence stays at medium."
    )
    assert pipeline.explain([_cand(0.9)], "strong", fallback=False).endswith(
        "but only one passage was cited, so confidence stays at medium."
    )
    assert pipeline.explain([_cand(0.55), _cand(0.5)], "moderate", fallback=False).endswith(
        "but top relevance is below 60% and the model did not rate its evidence strong, "
        "so confidence stays at medium."
    )
    assert pipeline.explain([_cand(0.3)], "strong", fallback=False).endswith(
        "but a single weakly relevant passage caps confidence at low."
    )
    assert pipeline.explain(high, "weak", fallback=False).endswith("which caps confidence at low.")
    assert "cited none of the passages" in pipeline.explain(high, "strong", fallback=True)
    assert pipeline.explain([], "strong", fallback=False) == "No passage was cited."
    # The reason is derived from the same rules as the category, for every combination.
    for cited in ([_cand(0.9)], [_cand(0.3)], high, [_cand(0.55), _cand(0.5)]):
        for strength in ("weak", "moderate", "strong", None):
            for fallback in (False, True):
                category = pipeline.categorise(cited, strength, fallback=fallback)
                reason = pipeline.explain(cited, strength, fallback=fallback)
                assert category in reason or (category == "high" and "high-confidence" in reason), (
                    category,
                    reason,
                )


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
    assert parse_generation("{}")["evidence_strength"] is None
    assert parse_generation('{"evidence_strength": "certain"}')["evidence_strength"] is None
    with pytest.raises(ModelUnavailable):
        parse_generation("not json")
    with pytest.raises(ModelUnavailable):
        parse_generation("[1, 2]")


def _cand(score):
    from retrieval import Candidate

    return Candidate(Chunk("health", "1", "p", "t", "x"), 1.0, 1.0, None, score)


def test_plant_now_uses_sydney_calendar_not_model_guess(store, monkeypatch):
    from datetime import datetime
    class OctoberClock:
        @staticmethod
        def now(tz):
            return datetime(2026, 10, 2, tzinfo=tz)
    monkeypatch.setattr(pipeline, "datetime", OctoberClock)
    store.replace_source("almanac", [
        Chunk("almanac", "basil", "reference", "Basil — plant reference", "Recorded planting months: September, October, November."),
        Chunk("almanac", "strawberry", "reference", "Strawberry — plant reference", "Recorded planting months: June, July."),
    ], documents=2)
    model = FakeAnswerer(AssertionError("Calendar lookup must not ask the model"))
    result = pipeline.answer("What can I plant now?", sources=("almanac",), top_k=5,
                             config=CONFIG, store=store, answerer=model)
    assert "October" in result["answer"] and "Basil" in result["answer"]
    assert "Strawberry" not in result["answer"]
    assert result["retrieval"]["current_date"] == "2026-10-02"
    assert result["model"] is None and not model.groundings
    assert [c["source_id"] for c in result["citations"]] == ["basil"]


def test_comparison_uses_both_saved_records(store):
    store.replace_source("almanac", [
        Chunk("almanac", "basil", "reference", "Basil — plant reference", "Sun needs: full sun. Water needs: moderate."),
        Chunk("almanac", "zucchini", "reference", "Zucchini — plant reference", "Sun needs: full sun. Water needs: high."),
    ], documents=2)
    model = FakeAnswerer(AssertionError("Direct record comparison must not need generation"))
    result = pipeline.answer("Compare basil and zucchini", sources=("almanac",), top_k=5,
                             config=CONFIG, store=store, answerer=model)
    assert "Water needs: moderate" in result["answer"]
    assert "Water needs: high" in result["answer"]
    assert len(result["citations"]) == 2 and not result["insufficient_context"]
    assert not model.groundings

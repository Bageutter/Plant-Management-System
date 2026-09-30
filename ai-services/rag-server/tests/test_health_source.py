"""Ingesting Plant Health records from a fake health API served over real HTTP."""

from __future__ import annotations

import os
import threading

import pytest
from flask import Flask, jsonify, request
from werkzeug.serving import make_server

from app import create_app
from sources import SourceUnavailable
from sources.health import chunks_for, fetch_assessments, ingest
from store import ChunkStore

RECORD = {
    "id": 3,
    "plant_ref": "Tomato, back bed",
    "description": "Lower leaves yellow, soil stays wet.",
    "has_image": False,
    "model": "qwen2.5vl:3b",
    "status": "at_risk",
    "health_score": 42,
    "score_band": "At risk — will worsen without action",
    "confidence": "medium",
    "confidence_reason": "Description covers watering but no photo.",
    "plant_identification": "Tomato (Solanum lycopersicum)",
    "summary": "Yellowing with constantly wet soil suggests overwatering.",
    "issues": [{"name": "Overwatering", "severity": "high", "evidence": "Soil stays wet"}],
    "recommendations": [{"action": "Reduce watering", "priority": "high", "details": "Let top 3cm dry."}],
    "missing_information": ["A photo of the leaves"],
    "created_at": "2026-09-20T05:30:00+00:00",
}


class FakeHealth:
    def __init__(self):
        self.records = [RECORD, {**RECORD, "id": 2, "plant_ref": "Basil", "issues": [], "recommendations": [], "missing_information": [], "description": None}]
        self.calls = []
        app = Flask("fake-health")

        @app.route("/health/plant-health-records/assessments")
        def list_assessments():
            self.calls.append(dict(request.args))
            limit = int(request.args.get("limit", 50))
            offset = int(request.args.get("offset", 0))
            return jsonify(self.records[offset : offset + limit])

        self.server = make_server("127.0.0.1", 0, app, threaded=True)
        self.url = f"http://127.0.0.1:{self.server.server_port}/health"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()


@pytest.fixture
def fake():
    server = FakeHealth()
    yield server
    server.stop()


def config_for(url):
    return {
        "HEALTH_SERVICE_URL": url,
        "HEALTH_PUBLIC_URL": "http://localhost:3000/health",
        "SERVICE_TIMEOUT": 5,
        "RAG_EMBED_MODEL": "",
    }


def test_chunks_cite_the_record_and_split_it_into_focused_passages():
    chunks = chunks_for(RECORD, "http://localhost:3000/health/")
    assert [c.part for c in chunks] == ["summary", "description", "issues", "recommendations", "missing"]
    assert all(c.title == "Assessment #3 — Tomato, back bed" for c in chunks)
    assert all(c.url == "http://localhost:3000/health/plant-health-records/3" for c in chunks)
    assert all(c.recorded_at == RECORD["created_at"] for c in chunks)
    summary = chunks[0].text
    assert "at risk" in summary and "42/100" in summary and "Model confidence: medium" in summary
    assert "Overwatering (high severity) — evidence: Soil stays wet" in chunks[2].text
    assert "Reduce watering (high priority): Let top 3cm dry." in chunks[3].text
    assert chunks[0].metadata["status"] == "at_risk"

    sparse = chunks_for({"id": 9, "status": "unknown", "created_at": None}, "http://x")
    assert [c.part for c in sparse] == ["summary"]
    assert "an unnamed plant" in sparse[0].text and "no health score" in sparse[0].text


def test_fetch_pages_until_exhausted(fake):
    fake.records = [{**RECORD, "id": i} for i in range(1, 8)]
    import sources.health as health_source

    original = health_source.PAGE_SIZE
    health_source.PAGE_SIZE = 3
    try:
        records = fetch_assessments(config_for(fake.url))
    finally:
        health_source.PAGE_SIZE = original
    assert [r["id"] for r in records] == list(range(1, 8))
    assert [c["offset"] for c in fake.calls] == ["0", "3", "6"]


def test_fetch_stops_when_a_server_without_offset_repeats_the_first_page(fake):
    def repeat_page(offset, limit):
        return fake.records  # ignores offset like the pre-Release-1 health service

    fake.calls.clear()
    fake_records = fake.records

    import sources.health as health_source

    original = health_source.PAGE_SIZE
    health_source.PAGE_SIZE = 2  # both records fit one page, so a naive loop would repeat
    try:
        records = fetch_assessments(config_for(fake.url))
    finally:
        health_source.PAGE_SIZE = original
    assert [r["id"] for r in records] == [r["id"] for r in fake_records]
    assert len(fake.calls) == 2  # second page returned nothing new -> stop


def test_ingest_replaces_the_source_and_reports_counts(fake, tmp_path):
    store = ChunkStore(os.path.join(tmp_path, "r.db"))
    result = ingest(config_for(fake.url), store)
    assert result == {
        "source": "health",
        "documents": 2,
        "chunks": 6,  # 5 for the tomato + 1 summary for the sparse basil record
        "embedded": False,
        "public_url": "http://localhost:3000/health",
    }
    assert store.get("health:3:issues").url == "http://localhost:3000/health/plant-health-records/3"

    # The basil record gets deleted in the health service; re-ingest drops its chunks.
    fake.records = [RECORD]
    result = ingest(config_for(fake.url), store)
    assert result["documents"] == 1 and result["chunks"] == 5
    assert store.get("health:2:summary") is None
    store.close()


def test_ingest_embeds_when_an_embedder_is_available(fake, tmp_path):
    class Embedder:
        def embed(self, texts):
            return [[1.0, float(i)] for i, _ in enumerate(texts)]

    store = ChunkStore(os.path.join(tmp_path, "e.db"))
    result = ingest(config_for(fake.url), store, embedder=Embedder())
    assert result["embedded"] is True
    assert store.get("health:3:summary").embedding == [1.0, 0.0]
    store.close()


def test_unreachable_health_service_is_a_502_not_a_crash(tmp_path, monkeypatch):
    monkeypatch.setattr("routes._ollama_reachable", lambda: False)
    app = create_app(
        {
            "TESTING": True,
            "RAG_ENABLED": True,
            "RAG_DATABASE_PATH": os.path.join(tmp_path, "x.db"),
            "HEALTH_SERVICE_URL": "http://127.0.0.1:1/health",
            "SERVICE_TIMEOUT": 1,
            "RAG_EMBED_MODEL": "",
        }
    )
    response = app.test_client().post("/rag/ingest/health")
    assert response.status_code == 502
    body = response.get_json()
    assert body["source"] == "health" and "could not be read" in body["error"]
    with pytest.raises(SourceUnavailable):
        fetch_assessments(app.config)
    app.extensions["chunk_store"].close()


def test_end_to_end_ingest_then_query_through_the_api(fake, tmp_path, monkeypatch):
    monkeypatch.setattr("routes._ollama_reachable", lambda: True)
    app = create_app(
        {
            "TESTING": True,
            "RAG_ENABLED": True,
            "RAG_DATABASE_PATH": os.path.join(tmp_path, "q.db"),
            **config_for(fake.url),
        }
    )

    class Answerer:
        model = "fake"

        def generate(self, question, grounding):
            ids = [p["chunk_id"] for p in grounding["passages"]]
            return {
                "answer": "Assessment #3 rated the tomato at risk and advised reducing watering.",
                "cited_chunk_ids": ids[:2],
                "evidence_strength": "strong",
                "insufficient_context": False,
            }

    monkeypatch.setattr("pipeline.build_answerer", lambda config: Answerer())
    client = app.test_client()

    ingested = client.post("/rag/ingest/health")
    assert ingested.status_code == 200 and ingested.get_json()["chunks"] == 6
    sources = {row["source"]: row for row in client.get("/rag/sources").get_json()}
    assert sources["health"]["implemented"] is True and sources["health"]["documents"] == 2
    assert sources["almanac"]["implemented"] is False

    response = client.post(
        "/rag/query", json={"question": "What should I do about the tomato in the back bed?", "sources": ["health"]}
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["insufficient_context"] is False and body["confidence"] in ("high", "medium")
    assert body["citations"][0]["url"].startswith("http://localhost:3000/health/plant-health-records/3")
    assert body["citations"][0]["source"] == "health"

    fragment = client.post(
        "/rag/query", data={"question": "What should I do about the tomato?"}, headers={"HX-Request": "true"}
    )
    html = fragment.get_data(as_text=True)
    assert fragment.status_code == 200 and "Assessment #3" in html and "confidence" in html.lower()
    assert 'data-model-confidence="strong"' in html and "Why " in html
    assert "model rated its evidence strong" in html
    app.extensions["chunk_store"].close()

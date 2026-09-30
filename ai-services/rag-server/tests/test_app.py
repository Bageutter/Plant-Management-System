"""Contract tests for the RAG server skeleton: liveness, switches, validation, stubs."""

from __future__ import annotations

import os

import pytest

from app import create_app
from store import Chunk, ChunkStore


@pytest.fixture
def app(tmp_path, monkeypatch):
    # Never touch a real Ollama from the test-suite.
    monkeypatch.setattr("routes._ollama_reachable", lambda: False)
    application = create_app(
        {
            "TESTING": True,
            "RAG_ENABLED": True,  # CI runs with RAG_ENABLED=false in the environment
            "RAG_DATABASE_PATH": os.path.join(tmp_path, "rag.db"),
            "OLLAMA_URL": "http://127.0.0.1:1",
        }
    )
    yield application
    application.extensions["chunk_store"].close()


@pytest.fixture
def client(app):
    return app.test_client()


def test_healthz_reports_degraded_without_ollama_and_counts_chunks(client):
    response = client.get("/healthz")
    assert response.status_code == 503
    body = response.get_json()
    assert body["service"] == "rag-server" and body["status"] == "degraded"
    assert body["enabled"] is True and body["chunks"] == 0
    assert body["sources"] == ["almanac", "health", "vgarden"]
    assert body["ai"]["reachable"] is False


def test_landing_page_renders_with_shared_header(client):
    response = client.get("/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Shared RAG server" in html and "Plant Management System" in html
    assert 'hx-post="/rag/query"' in html


def test_sources_lists_every_known_source_as_unindexed(client):
    body = client.get("/rag/sources").get_json()
    assert [row["source"] for row in body] == ["health", "almanac", "vgarden"]
    assert all(row["chunks"] == 0 and row["implemented"] is False for row in body)


@pytest.mark.parametrize("source", ["health", "almanac", "vgarden"])
def test_ingest_stubs_answer_501_and_name_the_tracking_reference(client, source):
    response = client.post(f"/rag/ingest/{source}")
    assert response.status_code == 501
    body = response.get_json()
    assert body["source"] == source and "not implemented" in body["error"]
    assert body["tracking"]


def test_ingest_unknown_source_is_404(client):
    response = client.post("/rag/ingest/users")
    assert response.status_code == 404
    assert "Unknown source" in response.get_json()["error"]


@pytest.mark.parametrize(
    "payload,fragment",
    [
        ({}, "non-empty 'question'"),
        ({"question": "   "}, "non-empty 'question'"),
        ({"question": "x" * 501}, "500 characters"),
        ({"question": "ok", "sources": ["users"]}, "Unknown sources"),
        ({"question": "ok", "sources": []}, "non-empty list"),
        ({"question": "ok", "top_k": 0}, "between 1 and 10"),
        ({"question": "ok", "top_k": "many"}, "must be an integer"),
    ],
)
def test_query_validation(client, payload, fragment):
    response = client.post("/rag/query", json=payload)
    assert response.status_code == 400
    assert fragment in response.get_json()["error"]


def test_valid_query_hits_the_not_implemented_pipeline_stub(client):
    response = client.post("/rag/query", json={"question": "Why are the tomato leaves yellow?"})
    assert response.status_code == 501
    body = response.get_json()
    assert "not implemented" in body["error"] and "No answer was generated" in body["error"]

    # The HTMX path renders the same failure as a fragment, never as fabricated prose.
    response = client.post(
        "/rag/query",
        data={"question": "Why are the tomato leaves yellow?", "sources": "health, almanac"},
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 501
    html = response.get_data(as_text=True)
    assert "could not answer" in html and 'data-status="501"' in html


def test_disabled_server_only_serves_liveness_and_landing(tmp_path, monkeypatch):
    monkeypatch.setattr("routes._ollama_reachable", lambda: True)
    app = create_app(
        {"TESTING": True, "RAG_ENABLED": False, "RAG_DATABASE_PATH": os.path.join(tmp_path, "x.db")}
    )
    client = app.test_client()
    healthz = client.get("/healthz")
    assert healthz.status_code == 200 and healthz.get_json()["enabled"] is False
    assert client.get("/").status_code == 200
    assert b"RAG is disabled" in client.get("/").data
    for method, path in [
        (client.get, "/rag/sources"),
        (client.post, "/rag/ingest/health"),
        (client.post, "/rag/query"),
    ]:
        response = method(path)
        assert response.status_code == 503, path
        assert response.get_json()["enabled"] is False
    app.extensions["chunk_store"].close()


def test_chunk_store_replace_is_idempotent_and_scoped_to_one_source(tmp_path):
    store = ChunkStore(os.path.join(tmp_path, "store.db"))
    health = [
        Chunk("health", "1", "summary", "Assessment #1", "Yellow leaves, wet soil.", url="/h/1"),
        Chunk("health", "1", "issues", "Assessment #1", "Overwatering (medium)."),
        Chunk("health", "2", "summary", "Assessment #2", "Aphids on basil.", embedding=[0.1, 0.2]),
    ]
    other = [Chunk("almanac", "tomato", "record", "Tomato", "Prefers well-draining soil.")]
    assert store.replace_source("health", health, documents=2) == 3
    store.replace_source("almanac", other, documents=1)
    assert store.count() == 4

    # Re-ingest with one record gone: its chunks disappear, other sources are untouched.
    store.replace_source("health", health[:2], documents=1)
    assert store.count() == 3
    assert [c.chunk_id for c in store.chunks(["health"])] == ["health:1:summary", "health:1:issues"]
    assert store.get("health:2:summary") is None
    assert store.get("almanac:tomato:record").text == "Prefers well-draining soil."

    rows = {row["source"]: row for row in store.sources()}
    assert rows["health"]["documents"] == 1 and rows["health"]["chunks"] == 2
    assert rows["almanac"]["chunks"] == 1

    round_trip = store.get("health:1:summary").to_dict()
    assert round_trip["url"] == "/h/1" and round_trip["chunk_id"] == "health:1:summary"
    store.close()

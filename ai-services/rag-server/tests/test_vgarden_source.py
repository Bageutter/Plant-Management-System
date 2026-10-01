"""Virtual Garden ingestion over the authenticated bulk export endpoint, including
the per-garden isolation that keeps one owner's question out of another's garden."""

import threading

import pytest
from flask import Flask, jsonify, request
from werkzeug.serving import make_server

from app import create_app
from sources import SourceUnavailable
from sources import vgarden
from store import ChunkStore


GARDENS = [
    {
        "garden_id": 1,
        "name": "Backyard",
        "location_label": "Melbourne",
        "climate_zone": "temperate",
        "areas": [
            {"id": 1, "garden_id": 1, "parent_area_id": None, "name": "North bed",
             "area_type": "bed", "pos_x": 0.0, "pos_y": 0.0, "width": 2.0, "length": 3.0, "notes": None},
        ],
        "containers": [],
        "plantings": [
            {
                "id": 1, "crop_name": "Tomato", "quantity": 3, "lifecycle_state": "growing",
                "growth_stage": "flowering", "planted_date": "2026-09-01",
                "expected_harvest_date": None, "location": "area: North bed",
            }
        ],
        "evidence_note": "Recorded garden state as entered by the owner.",
    },
    {
        "garden_id": 2,
        "name": "Rooftop",
        "location_label": None,
        "climate_zone": None,
        "areas": [],
        "containers": [],
        "plantings": [
            {
                "id": 2, "crop_name": "Basil", "quantity": 1, "lifecycle_state": "planned",
                "growth_stage": None, "planted_date": None, "expected_harvest_date": None, "location": None,
            }
        ],
        "evidence_note": "Recorded garden state as entered by the owner.",
    },
]


class FakeVgarden:
    """A minimal stand-in for vgarden's authenticated bulk export endpoint."""

    def __init__(self, token="test-token"):
        self.token = token
        self.calls = []
        self.gardens = GARDENS
        app = Flask("fake-vgarden")

        @app.before_request
        def record_call():
            self.calls.append((request.method, request.path, request.headers.get("Authorization")))

        @app.get("/vgarden/gardens/export")
        def export():
            if request.headers.get("Authorization") != f"Bearer {self.token}":
                return jsonify(error="unauthorized"), 401
            return jsonify(self.gardens)

        self.server = make_server("127.0.0.1", 0, app, threaded=True)
        self.url = f"http://127.0.0.1:{self.server.server_port}/vgarden"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()


@pytest.fixture
def fake():
    server = FakeVgarden()
    yield server
    server.stop()


@pytest.fixture
def store(tmp_path):
    index = ChunkStore(str(tmp_path / "rag.db"))
    yield index
    index.close()


def config_for(url, token="test-token"):
    return {
        "VGARDEN_SERVICE_URL": url,
        "VGARDEN_PUBLIC_URL": "http://localhost:3000/vgarden",
        "VGARDEN_SERVICE_TOKEN": token,
        "SERVICE_TIMEOUT": 2,
        "RAG_EMBED_MODEL": "",
    }


def test_ingest_authenticates_with_the_shared_service_token(fake, store):
    result = vgarden.ingest(config_for(fake.url), store)
    assert result == {
        "source": "vgarden",
        "documents": 2,
        "chunks": store.count(),
        "embedded": False,
        "public_url": "http://localhost:3000/vgarden",
    }
    assert fake.calls == [("GET", "/vgarden/gardens/export", "Bearer test-token")]


def test_wrong_token_is_reported_as_unavailable_not_silently_empty(fake, store):
    with pytest.raises(SourceUnavailable):
        vgarden.ingest(config_for(fake.url, token="wrong"), store)
    assert store.count() == 0


def test_each_garden_is_chunked_under_its_own_source_id(fake, store):
    vgarden.ingest(config_for(fake.url), store)

    mine = store.chunks(["vgarden"], source_id="1")
    theirs = store.chunks(["vgarden"], source_id="2")
    assert {c.part for c in mine} == {"summary", "areas", "plantings"}
    assert {c.part for c in theirs} == {"summary", "plantings"}
    assert all(c.source_id == "1" for c in mine)
    assert all(c.source_id == "2" for c in theirs)

    summary = store.get("vgarden:1:summary")
    assert "Backyard" in summary.text and "Melbourne" in summary.text and "temperate" in summary.text
    assert "1 area(s), 0 container(s), 1 planting(s)" in summary.text
    assert summary.url == "http://localhost:3000/vgarden/gardens/1/view"

    plantings = store.get("vgarden:1:plantings")
    assert "Tomato ×3" in plantings.text and "growing" in plantings.text and "North bed" in plantings.text
    assert "Backyard" not in store.get("vgarden:2:summary").text


def test_refresh_removes_deleted_gardens_without_touching_other_sources(fake, store):
    vgarden.ingest(config_for(fake.url), store)
    store.replace_source("health", [], documents=0)  # a sibling source, untouched by vgarden re-ingest
    fake.gardens = GARDENS[:1]
    result = vgarden.ingest(config_for(fake.url), store)
    assert result["documents"] == 1
    assert store.chunks(["vgarden"], source_id="2") == []
    assert store.chunks(["vgarden"], source_id="1") != []


def test_query_scoped_to_one_garden_never_sees_another(fake, store, monkeypatch):
    app = create_app(
        {
            "TESTING": True,
            "RAG_ENABLED": True,
            "RAG_DATABASE_PATH": str(store.path),
            **config_for(fake.url),
        }
    )

    class Answerer:
        model = "test-model"

        def generate(self, question, grounding):
            assert {p["source"] for p in grounding["passages"]} == {"vgarden"}
            passage = grounding["passages"][0]
            return {
                "answer": f"Found: {passage['text']}",
                "cited_chunk_ids": [passage["chunk_id"]],
                "evidence_strength": "strong",
                "insufficient_context": False,
            }

    monkeypatch.setattr("pipeline.build_answerer", lambda config: Answerer())
    client = app.test_client()
    try:
        assert client.post("/rag/ingest/vgarden").status_code == 200
        response = client.post(
            "/rag/query",
            json={"question": "What is growing?", "sources": ["vgarden"], "source_id": "1"},
        )
        assert response.status_code == 200
        body = response.get_json()
        assert body["insufficient_context"] is False
        assert {c["source_id"] for c in body["citations"]} == {"1"}
        assert "Basil" not in body["answer"] and "Rooftop" not in body["answer"]
    finally:
        app.extensions["chunk_store"].close()

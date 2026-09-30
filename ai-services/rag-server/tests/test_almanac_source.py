"""Exercise Almanac ingestion over HTTP, including a failed refresh of an existing index."""

from copy import deepcopy
import threading

import pytest
from flask import Flask, jsonify, request
from werkzeug.serving import make_server

from app import create_app
from embeddings import EmbeddingUnavailable
from sources import SourceUnavailable
from sources import almanac
from store import Chunk, ChunkStore


RECORDS = [
    {
        "kind": "plant",
        "key": "tomato",
        "id": 1,
        "name": "Tomato",
        "record": {
            "scientific_name": "Solanum lycopersicum",
            "summary": "A fruiting vegetable.",
            "water_needs": "moderate",
            "sun_needs": "full sun",
            "yield_qty": 4,
            "yield_unit": "kg",
            "diseases": ["Powdery mildew"],
            "pests": ["Aphids"],
            "guild_links": [
                {
                    "name": "Basil",
                    "function": "pollinator attractor",
                    "notes": "Allow some flowers.",
                }
            ],
            "rotation_group": {
                "name": "Solanums",
                "feeder_weight": "heavy",
                "is_rotation_exempt": False,
            },
        },
        "evidence_note": "General catalogue guidance, not a diagnosis. Missing fields are unknown; growing conditions vary.",
    },
    {
        "kind": "pest",
        "key": "1",
        "id": 1,
        "name": "Aphids",
        "description": "Sap-feeding insects.",
        "guide_available": True,
        "guide": {
            "intro": "Aphids cluster on tender shoots.",
            "signs": ["Sticky honeydew"],
            "control_steps": [{"title": "Rinse them off", "body": "Use a firm stream of water."}],
        },
        "evidence_note": "Recorded plant links are catalogue associations, not confirmed diagnoses.",
    },
    {
        "kind": "disease",
        "key": "1",
        "id": 1,
        "name": "Powdery mildew",
        "description": "A fungal disease group.",
        "guide_available": True,
        "guide": {
            "intro": "Powdery mildew forms pale, flour-like patches on leaves.",
            "signs": ["White or grey powdery patches"],
            "control_steps": [
                {"title": "Open up the plant", "body": "Improve airflow and avoid dense planting."}
            ],
            "spray_note": "Never apply horticultural oil within two weeks of sulfur.",
            "sources": [{"label": "Guide reference", "url": "https://example.org/mildew"}],
        },
        "evidence_note": "Recorded plant links are catalogue associations, not confirmed diagnoses.",
    },
    {
        "kind": "disease",
        "key": "2",
        "id": 2,
        "name": "Leaf spot",
        "description": "Spots on leaves.",
        "guide": None,
        "guide_available": False,
        "evidence_note": "A missing guide means management guidance is not available in this catalogue.",
    },
]


class FakeAlmanac:
    def __init__(self):
        self.records = deepcopy(RECORDS)
        self.calls = []
        self.fail_detail = None
        self.bad_detail = None
        self.bad_page = None
        app = Flask("fake-almanac")

        @app.before_request
        def record_call():
            self.calls.append((request.method, request.path, dict(request.args)))

        @app.get("/almanac/api/catalogue")
        def catalogue():
            limit = int(request.args["limit"])
            offset = int(request.args["offset"])
            assert 1 <= limit <= 50
            total = len(self.records)
            items = [
                {k: row[k] for k in ("kind", "key", "id", "name")}
                for row in self.records[offset : offset + limit]
            ]
            page = dict(
                items=items,
                total=total,
                offset=offset,
                limit=limit,
                next_offset=offset + limit if offset + limit < total else None,
            )
            if self.bad_page == "early_end":
                page["next_offset"] = None
            elif self.bad_page == "repeat" and offset:
                page["items"] = self.records[:limit]
            elif self.bad_page == "shape":
                page["items"] = "not a list"
            return jsonify(page)

        @app.get("/almanac/api/catalogue/<kind>/<key>")
        def detail(kind, key):
            if (kind, key) == self.fail_detail:
                return jsonify(error="temporarily unavailable"), 503
            if (kind, key) == self.bad_detail:
                return jsonify(kind=kind, key=key, name="Malformed entry", guide="not a guide")
            row = next(row for row in self.records if (row["kind"], row["key"]) == (kind, key))
            return jsonify(row)

        self.server = make_server("127.0.0.1", 0, app, threaded=True)
        self.url = f"http://127.0.0.1:{self.server.server_port}/almanac"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()


@pytest.fixture
def fake():
    server = FakeAlmanac()
    yield server
    server.stop()


@pytest.fixture
def store(tmp_path):
    index = ChunkStore(str(tmp_path / "rag.db"))
    yield index
    index.close()


def config_for(url):
    return {
        "ALMANAC_SERVICE_URL": url,
        "ALMANAC_PUBLIC_URL": "http://localhost:3000/almanac",
        "SERVICE_TIMEOUT": 2,
        "RAG_EMBED_MODEL": "",
    }


def test_ingest_reads_all_pages_and_keeps_caveats_with_browser_citations(fake, store, monkeypatch):
    monkeypatch.setattr(almanac, "PAGE_SIZE", 2)
    result = almanac.ingest(config_for(fake.url), store)
    assert result == {
        "source": "almanac",
        "documents": 4,
        "chunks": 4,
        "embedded": False,
        "public_url": "http://localhost:3000/almanac",
    }
    assert [args["offset"] for _, path, args in fake.calls if path.endswith("catalogue")] == [
        "0",
        "2",
    ]
    assert all(method == "GET" for method, _, _ in fake.calls)

    plant = store.get("almanac:plant:tomato:record")
    assert plant.title == "Tomato — plant reference"
    assert plant.url == "http://localhost:3000/almanac/plants/tomato"
    assert "Yield per plant: 4." in plant.text
    assert "Associated diseases: Powdery mildew" in plant.text
    assert "Recorded companion: Basil" in plant.text and "Rotation group: Solanums" in plant.text
    assert RECORDS[0]["evidence_note"] in plant.text
    assert "Missing fields are not recorded." in plant.text
    assert store.get("almanac:pest:1:record").url.endswith("/pests/1")
    disease = store.get("almanac:disease:1:record")
    assert disease.url.endswith("/diseases/1")
    assert "Improve airflow" in disease.text and "Never apply horticultural oil" in disease.text
    assert "not a diagnosis" in disease.text and "https://example.org/mildew" in disease.text
    missing = store.get("almanac:disease:2:record")
    assert "No management guide is available" in missing.text
    assert missing.metadata["guide_available"] is False


def test_refresh_removes_deleted_entries_without_touching_other_sources(fake, store):
    store.replace_source(
        "health", [Chunk("health", "1", "summary", "Existing health", "Wet soil")], 1
    )
    almanac.ingest(config_for(fake.url), store)
    fake.records = fake.records[:1]
    result = almanac.ingest(config_for(fake.url), store)
    assert result["documents"] == 1 and store.count() == 2
    assert store.get("almanac:disease:1:record") is None
    assert store.get("health:1:summary").text == "Wet soil"
    fake.records = []
    assert almanac.ingest(config_for(fake.url), store)["chunks"] == 0
    assert store.count() == 1


@pytest.mark.parametrize(
    "failure", ["detail_http", "detail_shape", "early_end", "repeat", "shape", "page_limit"]
)
def test_failed_or_incomplete_refresh_keeps_previous_index(fake, store, monkeypatch, failure):
    almanac.ingest(config_for(fake.url), store)
    original = [chunk.to_dict() for chunk in store.chunks()]
    monkeypatch.setattr(almanac, "PAGE_SIZE", 2)
    if failure == "detail_http":
        fake.fail_detail = ("disease", "1")
    elif failure == "detail_shape":
        fake.bad_detail = ("disease", "1")
    elif failure == "page_limit":
        monkeypatch.setattr(almanac, "MAX_PAGES", 1)
    else:
        fake.bad_page = failure
    with pytest.raises(SourceUnavailable):
        almanac.ingest(config_for(fake.url), store)
    assert [chunk.to_dict() for chunk in store.chunks()] == original


@pytest.mark.parametrize("available", [True, False])
def test_optional_embeddings_fall_back_to_lexical_when_unavailable(fake, store, available):
    class Embedder:
        def embed(self, texts):
            if not available:
                raise EmbeddingUnavailable("local Ollama is offline")
            return [[1.0, float(i)] for i, _ in enumerate(texts)]

    result = almanac.ingest(config_for(fake.url), store, embedder=Embedder())
    assert result["embedded"] is available
    assert (store.get("almanac:disease:1:record").embedding is not None) is available


def test_api_ingest_then_grounded_disease_query_and_source_failure(fake, tmp_path, monkeypatch):
    app = create_app(
        {
            "TESTING": True,
            "RAG_ENABLED": True,
            "RAG_DATABASE_PATH": str(tmp_path / "api.db"),
            **config_for(fake.url),
        }
    )

    class Answerer:
        model = "test-model"

        def generate(self, question, grounding):
            passage = next(
                item for item in grounding["passages"] if "Improve airflow" in item["text"]
            )
            assert "not a diagnosis" in passage["text"]
            return {
                "answer": "The powdery mildew guide recommends improving airflow and avoiding dense planting.",
                "cited_chunk_ids": [passage["chunk_id"]],
                "evidence_strength": "strong",
                "insufficient_context": False,
            }

    monkeypatch.setattr("pipeline.build_answerer", lambda config: Answerer())
    client = app.test_client()
    try:
        assert client.post("/rag/ingest/almanac").status_code == 200
        response = client.post(
            "/rag/query",
            json={"question": "How do I manage powdery mildew?", "sources": ["almanac"]},
        )
        assert response.status_code == 200
        body = response.get_json()
        assert body["insufficient_context"] is False and body["retrieval"]["mode"] == "lexical"
        assert body["citations"][0]["url"] == "http://localhost:3000/almanac/diseases/1"
        assert body["citations"][0]["source"] == "almanac"
        missing = client.post(
            "/rag/query", json={"question": "How do zebras migrate?", "sources": ["almanac"]}
        ).get_json()
        assert missing["insufficient_context"] is True and missing["answer"] is None
        fake.fail_detail = ("disease", "1")
        failure = client.post("/rag/ingest/almanac")
        assert failure.status_code == 502 and failure.get_json()["source"] == "almanac"
        assert app.extensions["chunk_store"].count() == 4
    finally:
        app.extensions["chunk_store"].close()

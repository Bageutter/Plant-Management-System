"""Frontend -> vgarden backend -> shared MCP / RAG servers, scoped to one garden.

MCP: the real shared server runs in-process and its HTTP calls are routed back
into the Flask app under test (httpx WSGI transport, mounted at /vgarden exactly
as the nginx proxy mounts it), so a tool call exercises the whole loop including
the service-token-authenticated snapshot endpoints. RAG: a fake RAG server
speaking the pinned contract runs on a real socket.
"""

from __future__ import annotations

import threading

import httpx
import pytest
from flask import Flask, jsonify, request
from werkzeug.exceptions import NotFound
from werkzeug.middleware.dispatcher import DispatcherMiddleware
from werkzeug.serving import make_server

from extensions import db
from integrations import GARDEN_TOOLS, IntegrationDisabled, IntegrationUnavailable, McpToolClient, RagClient
from models import Garden


def _make_garden(app, owner_id=1, name="Backyard"):
    with app.app_context():
        garden = Garden(owner_id=owner_id, name=name)
        db.session.add(garden)
        db.session.commit()
        return garden.id


@pytest.fixture
def mcp(app):
    """Point the backend's MCP client at the real shared server, in-process."""

    from server import create_server
    from settings import Settings

    # The shared server addresses the service as the proxy does (/vgarden/...), so
    # mount the Flask app under that prefix exactly like nginx does.
    mounted = DispatcherMiddleware(NotFound(), {"/vgarden": app})
    transport = httpx.WSGITransport(app=mounted)
    server = create_server(
        Settings(
            vgarden_url="http://127.0.0.1:3000/vgarden",
            vgarden_service_token=app.config["INTER_SERVICE_SECRET"],
        ),
        transport=transport,
    )
    app.extensions["mcp"] = McpToolClient(server, enabled=True, timeout=10)
    return app.extensions["mcp"]


class FakeRag:
    """Speaks the RAG server's response contract; records what it was asked."""

    def __init__(self):
        self.questions = []
        self.ingests = 0
        self.mode = "grounded"
        flask_app = Flask("fake-rag")

        @flask_app.route("/healthz")
        def healthz():
            return jsonify({"service": "rag-server", "status": "ok", "enabled": True, "chunks": 3})

        @flask_app.route("/rag/query", methods=["POST"])
        def query():
            payload = request.get_json()
            self.questions.append(payload)
            if self.mode == "reject":
                return jsonify({"error": "Provide a non-empty 'question'."}), 400
            if self.mode == "down":
                return jsonify({"error": "Ollama is down."}), 503
            if self.mode == "insufficient":
                return jsonify(
                    {
                        "question": payload["question"],
                        "answer": None,
                        "confidence": "insufficient",
                        "confidence_reason": "No indexed passage passed the relevance gate, so the model was not consulted.",
                        "model_confidence": None,
                        "insufficient_context": True,
                        "citations": [],
                        "retrieval": {"mode": "lexical", "candidates": 0, "considered": 3, "top_k": 5},
                        "model": None,
                        "duration_ms": 3,
                        "note": "No indexed passage was relevant enough.",
                    }
                )
            return jsonify(
                {
                    "question": payload["question"],
                    "answer": "This garden has a tomato planting in the north bed, growing well.",
                    "confidence": "medium",
                    "confidence_reason": "1 cited passage, top relevance 71%; model rated its evidence moderate.",
                    "model_confidence": "moderate",
                    "insufficient_context": False,
                    "citations": [
                        {
                            "chunk_id": "vgarden:1:plantings",
                            "source": "vgarden",
                            "source_id": "1",
                            "title": "Garden — Backyard",
                            "url": "http://localhost:3000/vgarden/gardens/1/view",
                            "excerpt": "Plantings in Backyard: Tomato ×3 — growing.",
                            "score": 0.71,
                        }
                    ],
                    "retrieval": {"mode": "lexical", "candidates": 2, "considered": 3, "top_k": 5},
                    "model": "fake-llm",
                    "duration_ms": 900,
                    "note": None,
                }
            )

        @flask_app.route("/rag/ingest/vgarden", methods=["POST"])
        def ingest():
            self.ingests += 1
            return jsonify({"source": "vgarden", "documents": 2, "chunks": 6, "embedded": False})

        self.server = make_server("127.0.0.1", 0, flask_app, threaded=True)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()


@pytest.fixture
def rag(app):
    fake = FakeRag()
    app.extensions["rag"] = RagClient(fake.url, enabled=True, timeout=5)
    yield fake
    fake.stop()


# -- status endpoints -----------------------------------------------------------------


def test_service_integrations_status_needs_no_login(app, client):
    """Config only (no owner data), so CI/ops can check wiring without a session —
    used by scripts/test/smoke-vgarden.sh."""

    app.extensions["mcp"] = McpToolClient("http://127.0.0.1:1/mcp", enabled=False)
    app.extensions["rag"] = RagClient("http://127.0.0.1:1", enabled=True)
    body = client.get("/integrations").get_json()
    assert body == {
        "mcp": {"enabled": False, "url": "http://127.0.0.1:1/mcp"},
        "rag": {"enabled": True, "url": "http://127.0.0.1:1"},
    }


def test_integrations_status_requires_login(app, client):
    garden_id = _make_garden(app)
    response = client.get(f"/gardens/{garden_id}/integrations", follow_redirects=False)
    assert response.status_code == 302


def test_integrations_status_404s_for_non_owner(app, client, login_as):
    garden_id = _make_garden(app, owner_id=1)
    login_as(2)
    assert client.get(f"/gardens/{garden_id}/integrations").status_code == 404


def test_integrations_status_reports_disabled_modes(app, client, login_as):
    garden_id = _make_garden(app)
    login_as(1)
    app.extensions["mcp"] = McpToolClient("http://127.0.0.1:1/mcp", enabled=False)
    app.extensions["rag"] = RagClient("http://127.0.0.1:1", enabled=False)
    body = client.get(f"/gardens/{garden_id}/integrations").get_json()
    assert body["mcp"] == {"enabled": False, "url": "http://127.0.0.1:1/mcp", "reachable": None}
    assert body["rag"] == {"enabled": False, "url": "http://127.0.0.1:1", "reachable": None}

    page = client.get(f"/gardens/{garden_id}/view").get_data(as_text=True)
    assert 'data-integration="mcp-disabled"' in page and 'data-integration="rag-disabled"' in page


def test_integrations_status_probes_when_enabled(app, client, login_as, mcp, rag):
    garden_id = _make_garden(app)
    login_as(1)
    body = client.get(f"/gardens/{garden_id}/integrations").get_json()
    assert body["mcp"]["enabled"] is True and body["mcp"]["reachable"] is True
    assert body["rag"]["enabled"] is True and body["rag"]["reachable"] is True
    assert body["rag"]["url"] == rag.url


# -- MCP through the backend, scoped to one garden ------------------------------------


def test_tools_endpoint_lists_the_shared_servers_tools(app, client, login_as, mcp):
    garden_id = _make_garden(app)
    login_as(1)
    response = client.get(f"/gardens/{garden_id}/tools")
    assert response.status_code == 200
    tools = {t["name"]: t for t in response.get_json()}
    assert set(tools) >= set(GARDEN_TOOLS)
    assert tools["get_garden_snapshot"]["vgarden"] is True
    assert tools["get_garden_snapshot"]["read_only"] is True
    assert tools["search_almanac_catalogue"]["vgarden"] is False


def test_run_tool_end_to_end_through_the_shared_mcp_server(app, client, login_as, mcp):
    garden_id = _make_garden(app, name="Backyard")
    login_as(1)

    response = client.post(f"/gardens/{garden_id}/tools/run", json={"tool": "get_garden_snapshot"})
    assert response.status_code == 200
    body = response.get_json()
    assert body["is_error"] is False and body["tool"] == "get_garden_snapshot"
    assert body["arguments"] == {"garden_id": garden_id}
    assert body["structured_content"]["name"] == "Backyard"

    fragment = client.post(
        f"/gardens/{garden_id}/tools/run",
        data={"tool": "list_garden_plantings"},
        headers={"HX-Request": "true"},
    )
    assert fragment.status_code == 200
    html = fragment.get_data(as_text=True)
    assert 'data-tool="list_garden_plantings"' in html and 'data-error="false"' in html
    assert "0 planting(s)" in html


def test_run_tool_always_uses_the_authenticated_garden_not_client_input(app, client, login_as, mcp):
    """A client-supplied `garden_id` must never override the garden in the URL —
    the whole point of the boundary documented in integrations.py."""

    mine = _make_garden(app, owner_id=1, name="Mine")
    someone_elses = _make_garden(app, owner_id=2, name="Someone else's")
    login_as(1)

    response = client.post(
        f"/gardens/{mine}/tools/run",
        json={"tool": "get_garden_snapshot", "garden_id": someone_elses},
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["arguments"] == {"garden_id": mine}
    assert body["structured_content"]["name"] == "Mine"


def test_run_tool_404s_for_non_owner(app, client, login_as, mcp):
    garden_id = _make_garden(app, owner_id=1)
    login_as(2)
    response = client.post(f"/gardens/{garden_id}/tools/run", json={"tool": "get_garden_snapshot"})
    assert response.status_code == 404


def test_run_tool_rejects_unknown_tool_before_calling_the_server(app, client, login_as, mcp):
    garden_id = _make_garden(app)
    login_as(1)
    response = client.post(f"/gardens/{garden_id}/tools/run", json={"tool": "search_almanac_catalogue"})
    assert response.status_code == 400
    assert "Provide one of" in response.get_json()["error"]


def test_run_tool_when_mcp_disabled_or_unreachable(app, client, login_as):
    garden_id = _make_garden(app)
    login_as(1)

    app.extensions["mcp"] = McpToolClient("http://127.0.0.1:1/mcp", enabled=False)
    disabled = client.post(f"/gardens/{garden_id}/tools/run", json={"tool": "get_garden_snapshot"})
    assert disabled.status_code == 503 and "disabled" in disabled.get_json()["error"]
    assert client.get(f"/gardens/{garden_id}/tools").status_code == 503

    app.extensions["mcp"] = McpToolClient("http://127.0.0.1:1/mcp", enabled=True, timeout=2)
    down = client.post(
        f"/gardens/{garden_id}/tools/run",
        data={"tool": "get_garden_snapshot"},
        headers={"HX-Request": "true"},
    )
    assert down.status_code == 502 and b"could not be reached" in down.data

    with pytest.raises(IntegrationDisabled):
        McpToolClient("http://127.0.0.1:1/mcp", enabled=False).list_tools()
    with pytest.raises(IntegrationUnavailable):
        McpToolClient("http://127.0.0.1:1/mcp", enabled=True, timeout=2).list_tools()


# -- RAG through the backend, scoped to one garden ------------------------------------


def test_ask_scopes_the_question_to_this_garden_only(app, client, login_as, rag):
    garden_id = _make_garden(app)
    login_as(1)
    response = client.post(f"/gardens/{garden_id}/ask", json={"question": "What's planted here?"})
    assert response.status_code == 200
    body = response.get_json()
    assert body["confidence"] == "medium" and body["citations"][0]["source"] == "vgarden"
    assert rag.questions[-1] == {
        "question": "What's planted here?",
        "sources": ["vgarden"],
        "source_id": str(garden_id),
    }


def test_ask_renders_grounded_answer_with_citation_and_confidence(app, client, login_as, rag):
    garden_id = _make_garden(app)
    login_as(1)
    fragment = client.post(
        f"/gardens/{garden_id}/ask",
        data={"question": "What's planted here?"},
        headers={"HX-Request": "true"},
    )
    html = fragment.get_data(as_text=True)
    assert fragment.status_code == 200
    assert 'data-confidence="medium"' in html and "Medium confidence" in html
    assert "Garden — Backyard" in html or "tomato planting" in html
    assert "answered locally by fake-llm" in html


def test_ask_renders_insufficient_context(app, client, login_as, rag):
    garden_id = _make_garden(app)
    login_as(1)
    rag.mode = "insufficient"
    fragment = client.post(
        f"/gardens/{garden_id}/ask",
        data={"question": "Capital of France?"},
        headers={"HX-Request": "true"},
    )
    html = fragment.get_data(as_text=True)
    assert fragment.status_code == 200
    assert 'data-confidence="insufficient"' in html and "Not enough relevant context" in html
    assert 'data-refusal="gate"' in html


def test_ask_404s_for_non_owner(app, client, login_as, rag):
    garden_id = _make_garden(app, owner_id=1)
    login_as(2)
    response = client.post(f"/gardens/{garden_id}/ask", json={"question": "What's planted here?"})
    assert response.status_code == 404
    assert rag.questions == []


def test_ask_validation_and_failures(app, client, login_as, rag):
    garden_id = _make_garden(app)
    login_as(1)
    assert client.post(f"/gardens/{garden_id}/ask", json={}).status_code == 400
    assert client.post(f"/gardens/{garden_id}/ask", json={"question": "x" * 501}).status_code == 400

    rag.mode = "reject"
    rejected = client.post(f"/gardens/{garden_id}/ask", json={"question": "hello"})
    assert rejected.status_code == 400 and "non-empty" in rejected.get_json()["error"]

    rag.mode = "down"
    down = client.post(f"/gardens/{garden_id}/ask", json={"question": "hello"})
    assert down.status_code == 502 and "Ollama is down" in down.get_json()["error"]

    app.extensions["rag"] = RagClient("http://127.0.0.1:1", enabled=False)
    disabled = client.post(
        f"/gardens/{garden_id}/ask", data={"question": "hello"}, headers={"HX-Request": "true"}
    )
    assert disabled.status_code == 503 and b"disabled" in disabled.data


def test_sync_garden_index_triggers_ingest_on_the_rag_server(app, client, login_as, rag):
    garden_id = _make_garden(app)
    login_as(1)
    response = client.post(f"/gardens/{garden_id}/ask/sync", headers={"HX-Request": "true"})
    assert response.status_code == 200 and rag.ingests == 1
    assert b"6 passages" in response.data

    as_json = client.post(f"/gardens/{garden_id}/ask/sync")
    assert as_json.status_code == 200 and as_json.get_json()["chunks"] == 6

"""Frontend → health backend → shared MCP / RAG servers.

MCP: the real shared server runs in-process and its HTTP calls are routed back into
the Flask app under test (httpx WSGI transport), so a tool call exercises the whole
loop. RAG: a fake RAG server speaking the pinned contract runs on a real socket.
"""

from __future__ import annotations

import threading

import httpx
import pytest
from flask import Flask, jsonify, request
from werkzeug.exceptions import NotFound
from werkzeug.middleware.dispatcher import DispatcherMiddleware
from werkzeug.serving import make_server

from conftest import make_assessment
from integrations import (
    HEALTH_TOOLS,
    IntegrationDisabled,
    IntegrationUnavailable,
    McpToolClient,
    RagClient,
    coerce_tool_args,
)


@pytest.fixture
def mcp(app):
    """Point the backend's MCP client at the real shared server, in-process."""

    from server import create_server
    from settings import Settings

    # The shared server addresses the service as the proxy does (/health/...), so mount
    # the Flask app under that prefix exactly like nginx does.
    mounted = DispatcherMiddleware(NotFound(), {"/health": app})
    transport = httpx.WSGITransport(app=mounted)
    server = create_server(Settings(health_url="http://127.0.0.1:3000/health"), transport=transport)
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
            if self.mode == "model_insufficient":
                return jsonify(
                    {
                        "question": payload["question"],
                        "answer": None,
                        "confidence": "insufficient",
                        "confidence_reason": "The model judged the retrieved passages insufficient to answer this question (its own evidence rating: weak).",
                        "model_confidence": "weak",
                        "insufficient_context": True,
                        "citations": [],
                        "retrieval": {"mode": "lexical", "candidates": 2, "considered": 3, "top_k": 5},
                        "model": "fake-llm",
                        "duration_ms": 800,
                        "note": "The retrieved passages did not contain enough to answer this question.",
                    }
                )
            return jsonify(
                {
                    "question": payload["question"],
                    "answer": "Assessment #1 rated the tomato at risk from overwatering.",
                    "confidence": "medium",
                    "confidence_reason": "1 cited passage, top relevance 71%; model rated its evidence moderate.",
                    "model_confidence": "moderate",
                    "insufficient_context": False,
                    "citations": [
                        {
                            "chunk_id": "health:1:summary",
                            "source": "health",
                            "source_id": "1",
                            "title": "Assessment #1 — Tomato, back bed",
                            "url": "http://localhost:3000/health/plant-health-records/1",
                            "excerpt": "Status: at risk (health score 45/100).",
                            "score": 0.71,
                        }
                    ],
                    "retrieval": {"mode": "lexical", "candidates": 2, "considered": 3, "top_k": 5},
                    "model": "fake-llm",
                    "duration_ms": 900,
                    "note": None,
                }
            )

        @flask_app.route("/rag/ingest/health", methods=["POST"])
        def ingest():
            self.ingests += 1
            return jsonify({"source": "health", "documents": 2, "chunks": 6, "embedded": False})

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


# -- argument whitelist ----------------------------------------------------------


def test_tool_argument_whitelist_and_coercion():
    assert coerce_tool_args("list_health_assessments", {"limit": "5", "status": "AT_RISK", "plant_ref": " Tomato "}) == {
        "plant_ref": "Tomato",
        "status": "at_risk",
        "limit": 5,
    }
    assert coerce_tool_args("health_service_status", {"anything": "ignored"}) == {}
    with pytest.raises(ValueError, match="required"):
        coerce_tool_args("summarise_plant_health_history", {"plant_ref": ""})
    with pytest.raises(ValueError, match="whole number"):
        coerce_tool_args("get_health_assessment", {"assessment_id": "abc"})
    with pytest.raises(ValueError, match="one of"):
        coerce_tool_args("list_health_assessments", {"status": "dead"})
    with pytest.raises(ValueError, match="Unknown or non-health"):
        coerce_tool_args("search_almanac_catalogue", {"query": "x"})
    assert set(HEALTH_TOOLS) == {
        "health_service_status",
        "list_health_assessments",
        "get_health_assessment",
        "summarise_plant_health_history",
        "assess_plant_health",
    }


# -- status endpoint ---------------------------------------------------------------


def test_integrations_status_reports_disabled_modes_without_calling_out(app, client):
    app.extensions["mcp"] = McpToolClient("http://127.0.0.1:1/mcp", enabled=False)
    app.extensions["rag"] = RagClient("http://127.0.0.1:1", enabled=False)
    body = client.get("/plant-health-records/integrations").get_json()
    assert body["mcp"] == {"enabled": False, "url": "http://127.0.0.1:1/mcp", "reachable": None}
    assert body["rag"] == {"enabled": False, "url": "http://127.0.0.1:1", "reachable": None}

    page = client.get("/plant-health-records/").get_data(as_text=True)
    assert 'data-integration="mcp-disabled"' in page and 'data-integration="rag-disabled"' in page
    assert "MCP off" in page and "RAG off" in page


def test_integrations_status_probes_when_enabled(app, client, mcp, rag):
    body = client.get("/plant-health-records/integrations").get_json()
    assert body["mcp"]["enabled"] is True and body["mcp"]["reachable"] is True
    assert body["rag"]["enabled"] is True and body["rag"]["reachable"] is True
    assert body["rag"]["url"] == rag.url

    app.extensions["rag"] = RagClient("http://127.0.0.1:1", enabled=True, timeout=1)
    assert client.get("/plant-health-records/integrations").get_json()["rag"]["reachable"] is False


# -- MCP through the backend ---------------------------------------------------------


def test_tools_endpoint_lists_the_shared_servers_tools(client, mcp):
    response = client.get("/plant-health-records/tools")
    assert response.status_code == 200
    tools = {t["name"]: t for t in response.get_json()}
    assert set(tools) >= set(HEALTH_TOOLS)
    assert tools["list_health_assessments"]["health"] is True and tools["list_health_assessments"]["read_only"] is True
    assert tools["assess_plant_health"]["read_only"] is False
    assert tools["search_almanac_catalogue"]["health"] is False


def test_run_tool_end_to_end_through_the_shared_mcp_server(client, mcp):
    first = make_assessment(client, plant_ref="Tomato, back bed")
    make_assessment(client, plant_ref="Basil")

    response = client.post(
        "/plant-health-records/tools/run",
        json={"tool": "list_health_assessments", "plant_ref": "Tomato, back bed", "limit": 5},
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["is_error"] is False and body["tool"] == "list_health_assessments"
    items = body["structured_content"]["items"]
    assert [i["id"] for i in items] == [first["id"]]
    assert items[0]["url"].endswith(f"/health/plant-health-records/{first['id']}")

    # HTMX gets a rendered fragment of the same structured result.
    fragment = client.post(
        "/plant-health-records/tools/run",
        data={"tool": "summarise_plant_health_history", "plant_ref": "Tomato, back bed", "limit": "10"},
        headers={"HX-Request": "true"},
    )
    assert fragment.status_code == 200
    html = fragment.get_data(as_text=True)
    assert 'data-tool="summarise_plant_health_history"' in html and 'data-error="false"' in html
    assert "1 assessment(s)" in html and "Overwatering" in html

    status = client.post("/plant-health-records/tools/run", json={"tool": "health_service_status"})
    assert status.get_json()["structured_content"]["ai_reachable"] is True

    one = client.post(
        "/plant-health-records/tools/run", json={"tool": "get_health_assessment", "assessment_id": first["id"]}
    )
    assert one.get_json()["structured_content"]["issues"][0]["name"] == "Overwatering"


def test_run_tool_creates_a_record_via_mcp_and_reports_tool_errors(client, mcp, fake_ai):
    response = client.post(
        "/plant-health-records/tools/run",
        json={"tool": "assess_plant_health", "description": "Curling leaves", "plant_ref": "Chilli"},
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["is_error"] is False and body["structured_content"]["plant_ref"] == "Chilli"
    assert fake_ai.calls[-1]["description"] == "Curling leaves"
    assert len(client.get("/plant-health-records/assessments").get_json()) == 1

    missing = client.post(
        "/plant-health-records/tools/run", json={"tool": "get_health_assessment", "assessment_id": 999}
    )
    assert missing.status_code == 200  # the tool ran; the *tool* reports the error
    assert missing.get_json()["is_error"] is True and "not found" in missing.get_json()["text"]

    fragment = client.post(
        "/plant-health-records/tools/run",
        data={"tool": "get_health_assessment", "assessment_id": "999"},
        headers={"HX-Request": "true"},
    )
    assert 'data-error="true"' in fragment.get_data(as_text=True)


def test_run_tool_rejects_bad_input_before_calling_the_server(client, mcp):
    for payload, fragment in [
        ({}, "Provide a 'tool'"),
        ({"tool": "search_almanac_catalogue"}, "non-health"),
        ({"tool": "get_health_assessment", "assessment_id": "x"}, "whole number"),
        ({"tool": "assess_plant_health"}, "required"),
    ]:
        response = client.post("/plant-health-records/tools/run", json=payload)
        assert response.status_code == 400, payload
        assert fragment in response.get_json()["error"]


def test_run_tool_when_mcp_disabled_or_unreachable(app, client):
    app.extensions["mcp"] = McpToolClient("http://127.0.0.1:1/mcp", enabled=False)
    disabled = client.post("/plant-health-records/tools/run", json={"tool": "health_service_status"})
    assert disabled.status_code == 503 and "disabled" in disabled.get_json()["error"]
    assert client.get("/plant-health-records/tools").status_code == 503

    app.extensions["mcp"] = McpToolClient("http://127.0.0.1:1/mcp", enabled=True, timeout=2)
    down = client.post(
        "/plant-health-records/tools/run",
        data={"tool": "health_service_status"},
        headers={"HX-Request": "true"},
    )
    assert down.status_code == 502 and b"could not be reached" in down.data

    with pytest.raises(IntegrationDisabled):
        McpToolClient("http://127.0.0.1:1/mcp", enabled=False).list_tools()
    with pytest.raises(IntegrationUnavailable):
        McpToolClient("http://127.0.0.1:1/mcp", enabled=True, timeout=2).list_tools()


# -- RAG through the backend ---------------------------------------------------------


def test_ask_returns_grounded_answer_with_citations_and_confidence(client, rag):
    response = client.post(
        "/plant-health-records/ask", json={"question": "What is wrong with the tomato?"}
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["confidence"] == "medium" and body["citations"][0]["source"] == "health"
    assert rag.questions[-1] == {"question": "What is wrong with the tomato?", "sources": ["health"]}

    fragment = client.post(
        "/plant-health-records/ask",
        data={"question": "What is wrong with the tomato?"},
        headers={"HX-Request": "true"},
    )
    html = fragment.get_data(as_text=True)
    assert fragment.status_code == 200
    assert 'data-confidence="medium"' in html and "Medium confidence" in html
    assert "Assessment #1 — Tomato, back bed" in html and "relevance 71%" in html
    assert "answered locally by fake-llm" in html
    # The model's own rating and the reason for the category are shown, labelled honestly.
    assert body["model_confidence"] == "moderate"
    assert "Why medium confidence:" in html and "model rated its evidence moderate" in html
    assert 'data-model-confidence="moderate"' in html and "moderate evidence" in html
    assert "self-reported by fake-llm" in html


def test_ask_renders_the_insufficient_context_response(client, rag):
    rag.mode = "insufficient"
    fragment = client.post(
        "/plant-health-records/ask",
        data={"question": "Capital of France?"},
        headers={"HX-Request": "true"},
    )
    html = fragment.get_data(as_text=True)
    assert fragment.status_code == 200
    assert 'data-confidence="insufficient"' in html and "Not enough relevant context" in html
    assert 'data-refusal="gate"' in html and "Sync records to the knowledge base" in html
    assert "fake-llm" not in html
    # No model was consulted, so there is a reason but no model rating to show.
    assert "model was not consulted" in html
    assert "data-model-confidence" not in html


def test_ask_renders_a_model_declared_refusal_with_its_rating(client, rag):
    rag.mode = "model_insufficient"
    fragment = client.post(
        "/plant-health-records/ask",
        data={"question": "Was the tomato fertilised?"},
        headers={"HX-Request": "true"},
    )
    html = fragment.get_data(as_text=True)
    assert fragment.status_code == 200
    assert 'data-confidence="insufficient"' in html and 'data-refusal="model"' in html
    # Relevant records were retrieved, so the card must not claim nothing was indexed
    # or suggest re-syncing; it attributes the refusal to the model and shows its rating.
    assert "2 related passages were retrieved" in html and "do not" in html
    assert "Sync records to the knowledge base" not in html
    assert 'data-model-confidence="weak"' in html and "weak evidence" in html
    assert "self-reported by fake-llm" in html and "assessed locally by fake-llm" in html
    assert "Why insufficient context:" in html
    assert "<h4" not in html  # no Sources list for a refusal


def test_ask_validation_and_failures(app, client, rag):
    assert client.post("/plant-health-records/ask", json={}).status_code == 400
    assert client.post("/plant-health-records/ask", json={"question": "x" * 501}).status_code == 400

    rag.mode = "reject"
    rejected = client.post("/plant-health-records/ask", json={"question": "hello"})
    assert rejected.status_code == 400 and "non-empty" in rejected.get_json()["error"]

    rag.mode = "down"
    down = client.post("/plant-health-records/ask", json={"question": "hello"})
    assert down.status_code == 502 and "Ollama is down" in down.get_json()["error"]

    app.extensions["rag"] = RagClient("http://127.0.0.1:1", enabled=False)
    disabled = client.post(
        "/plant-health-records/ask", data={"question": "hello"}, headers={"HX-Request": "true"}
    )
    assert disabled.status_code == 503 and b"disabled" in disabled.data

    app.extensions["rag"] = RagClient("http://127.0.0.1:1", enabled=True, timeout=1)
    unreachable = client.post("/plant-health-records/ask", json={"question": "hello"})
    assert unreachable.status_code == 502 and "could not be reached" in unreachable.get_json()["error"]


def test_sync_records_triggers_ingest_on_the_rag_server(client, rag):
    response = client.post("/plant-health-records/ask/sync", headers={"HX-Request": "true"})
    assert response.status_code == 200 and rag.ingests == 1
    assert b"6 passages" in response.data

    as_json = client.post("/plant-health-records/ask/sync")
    assert as_json.status_code == 200 and as_json.get_json()["chunks"] == 6

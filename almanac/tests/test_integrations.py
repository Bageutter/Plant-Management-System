"""UI/backend contracts without calling a local model during CI."""

import httpx
import pytest

from app import create_app
import integrations


@pytest.fixture
def app(tmp_path):
    return create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'almanac.db'}",
        "PLANT_IMAGE_FOLDER": str(tmp_path / "images"),
        "MCP_ENABLED": True,
        "RAG_ENABLED": True,
    })


def test_mcp_allows_only_bounded_read_only_tools_and_renders_links(app, monkeypatch):
    calls = []

    async def call(target, tool, arguments):
        calls.append((tool, arguments))
        return {"tool": tool, "is_error": False, "structured_content": {
            "total": 1, "items": [{"kind": "disease", "id": 7, "key": "7", "name": "<script>Mildew</script>"}],
        }, "text": ""}

    monkeypatch.setattr(integrations, "_call_tool", call)
    client = app.test_client()
    page = client.get("/integrations", headers={"Accept": "text/html"})
    assert page.status_code == 200 and b"Ask with sources" in page.data
    assert page.mimetype == "text/html" and "Accept" in page.vary
    result = client.post("/integrations/mcp", data={"query": "mildew", "kind": "disease"}, headers={"X-Forwarded-Prefix": "/almanac"})
    assert result.status_code == 200
    assert b'/almanac/diseases/7' in result.data and b'&lt;script&gt;' in result.data
    assert calls == [("search_almanac_catalogue", {"query": "mildew", "kind": "disease", "limit": 20})]
    for body in [[], {"tool": "assess_plant_health"}, {"limit": True}, {"limit": 51}, {"limit": 1.5}, {"kind": "private"}, {"query": ["tomato"]}, {"tool": "get_almanac_plant", "slug": "../secret"}]:
        assert client.post("/integrations/mcp", json=body).status_code == 400
    assert len(calls) == 1
    app.config["MCP_ENABLED"] = False
    assert client.post("/integrations/mcp", json={}).status_code == 503
    assert len(calls) == 1


def test_rag_preserves_grounding_refusal_and_unavailable_states(app, monkeypatch):
    calls = []
    answer = {"answer": "Improve airflow.", "insufficient_context": False, "confidence": "medium", "confidence_reason": "One saved guide.", "citations": [{"title": "Powdery mildew", "url": "http://localhost:3000/almanac/diseases/1", "excerpt": "Give plants room."}]}

    def ask(path, body):
        calls.append((path, body))
        return answer

    monkeypatch.setattr(integrations, "_rag_request", ask)
    client = app.test_client()
    result = client.post("/integrations/rag", data={"question": "Mildew prevention?"})
    assert result.status_code == 200
    assert b"Medium confidence" in result.data and b"References used" in result.data
    assert calls[0] == ("/rag/query", {"question": "Mildew prevention?", "sources": ["almanac"]})
    answer.update(answer="Not enough saved information.", insufficient_context=True, confidence="insufficient", citations=[])
    result = client.post("/integrations/rag", data={"question": "Who won the football?"})
    assert b"Insufficient context" in result.data and b"References used" not in result.data
    for body in [[], {"question": ""}, {"question": "x" * 501}, {"question": 123}]:
        assert client.post("/integrations/rag", json=body).status_code == 400

    def unavailable(*args):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(integrations, "_rag_request", unavailable)
    assert client.post("/integrations/rag", json={"question": "Mildew?"}).status_code == 502
    app.config["RAG_ENABLED"] = False
    assert client.post("/integrations/rag", json={"question": "Mildew?"}).status_code == 503


def test_index_refresh_requires_csrf_and_login(app):
    client = app.test_client()
    assert client.post("/integrations/rag/sync").status_code == 400
    app.config["WTF_CSRF_ENABLED"] = False
    assert client.post("/integrations/rag/sync").status_code == 401


@pytest.mark.parametrize("accept", [None, "*/*", "application/json", "application/json;q=1,text/html;q=0.5"])
@pytest.mark.parametrize("enabled", [False, True])
def test_integration_status_reports_configured_modes_for_review_clients(app, accept, enabled):
    app.config.update(
        MCP_ENABLED=enabled, MCP_SERVER_URL="http://127.0.0.1:5105/mcp",
        RAG_ENABLED=enabled, RAG_SERVER_URL="http://127.0.0.1:5106",
        MULTI_AGENT_ENABLED=enabled, MULTI_AGENT_SERVER_URL="http://127.0.0.1:8013",
    )
    response = app.test_client().get("/integrations", headers={"Accept": accept} if accept else {})
    assert response.status_code == 200 and response.mimetype == "application/json"
    assert response.json == {
        "mcp": {"enabled": enabled, "url": "http://127.0.0.1:5105/mcp"},
        "rag": {"enabled": enabled, "url": "http://127.0.0.1:5106"},
        "multi_agent": {"enabled": enabled, "url": "http://127.0.0.1:8013"},
    }
    assert "Accept" in response.vary

"""Exercise the public boundary and real MCP discovery/calls over both transports."""

import asyncio
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time

import httpx
from mcp import Client
from mcp.client.stdio import StdioServerParameters
import pytest
from werkzeug.serving import make_server

from app import create_app
from extensions import db
from garden_data import refresh_garden_wording, seed_guilds
from import_notion import import_notion, seed_estimates
from mcp_server import AlmanacClient, create_server
from models import AIChatMessage, Disease, Pest, PlantReference
from mcp_evidence import collect, run_tool
from mcp_review import generate, review_evidence, write_reports


@pytest.fixture
def catalogue(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'catalogue.db'}",
            "PLANT_IMAGE_FOLDER": str(tmp_path / "images"),
        }
    )
    with app.app_context():
        import_notion()
        seed_estimates()
        refresh_garden_wording()
        seed_guilds()
        db.session.add(
            AIChatMessage(owner_key="user:999", role="user", content="PRIVATE_CHAT_SENTINEL")
        )
        db.session.commit()
        yield app


def test_public_catalogue_search_pages_and_literal_search(catalogue):
    client = catalogue.test_client()
    first = client.get("/api/catalogue?limit=2").json
    second = client.get("/api/catalogue?limit=2&offset=2").json
    assert first["next_offset"] == 2
    assert not {x["uri"] for x in first["items"]} & {x["uri"] for x in second["items"]}
    assert (
        first["total"] == PlantReference.query.count() + Pest.query.count() + Disease.query.count()
    )
    assert client.get("/api/catalogue?q=APHIDS&kind=pest").json["items"][0]["name"] == "Aphids"
    assert client.get("/api/catalogue?q=Solanum%20lycopersicum").json["total"] >= 1
    for query in ["%", "_", "' OR 1=1 --", "no-such-plant"]:
        assert client.get("/api/catalogue", query_string={"q": query}).json["items"] == []
    for query in ["limit=0", "limit=51", "offset=-1", "limit=no", "kind=users", "q=" + "a" * 121]:
        response = client.get("/api/catalogue?" + query)
        assert response.status_code == 400
        assert response.json["error"]
    # Prefixes survive when the API is called through the shared reverse proxy.
    proxied = client.get("/api/catalogue?q=Aphids", headers={"X-Forwarded-Prefix": "/almanac"})
    assert proxied.json["items"][0]["path"].startswith("/almanac/pests/")


def test_public_details_preserve_evidence_and_make_no_writes(catalogue):
    client = catalogue.test_client()
    before = [p.to_dict() for p in PlantReference.query.order_by(PlantReference.id)]
    payload = client.get("/api/catalogue/plant/lettuce").json
    assert "yield_qty" in payload["record"]["estimated_fields"]
    assert payload["pests"] and payload["record"]["guild_links"]
    aphids = Pest.query.filter_by(name="Aphids").one()
    guide = client.get(f"/api/catalogue/pest/{aphids.id}?limit=1").json
    assert guide["guide_available"] and guide["guide"]["sources"]
    assert len(guide["plants"]) == 1 and guide["next_offset"] == 1
    ally = guide["guide"]["companions"][0]
    assert ally["plant"]["uri"] == "almanac://plants/alyssum"
    mildew = Disease.query.filter_by(name="Powdery mildew").one()
    assert client.get(f"/api/catalogue/disease/{mildew.id}").json["guide"]["spray_note"]
    slugs = Pest.query.filter_by(name="Slugs and snails").one()
    assert client.get(f"/api/catalogue/pest/{slugs.id}").json["guide_available"] is False
    for path in ["plant/no-such-plant", "pest/999999", "disease/999999"]:
        response = client.get("/api/catalogue/" + path)
        assert response.status_code == 404 and response.json["error"]
    assert "plants_per_m2" not in payload["record"]
    assert (
        client.get("/api/catalogue/plant/lettuce/calculate?amount=10&unit=head").status_code == 404
    )
    for method in [client.post, client.put, client.patch, client.delete]:
        assert method("/api/catalogue/plant/lettuce").status_code in (400, 405)
    assert [p.to_dict() for p in PlantReference.query.order_by(PlantReference.id)] == before
    assert "PRIVATE_CHAT_SENTINEL" not in json.dumps([payload, guide])


@pytest.mark.parametrize(
    "url", ["file:///tmp/data", "http://user:secret@localhost", "http://x/?key=secret"]
)
def test_adapter_rejects_invalid_base_urls(url):
    with pytest.raises(ValueError):
        AlmanacClient(url)


def test_adapter_handles_errors_and_never_follows_redirects():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(302, headers={"location": "http://other-service/private"})

    api = AlmanacClient("http://almanac/almanac", transport=httpx.MockTransport(handler))
    with pytest.raises(ValueError, match="HTTP 302"):
        api.get("/plant/lettuce")
    assert len(calls) == 1
    assert calls[0].url.path == "/almanac/api/catalogue/plant/lettuce"
    assert calls[0].method == "GET"

    def offline(request):
        raise httpx.ConnectError("internal connection details")

    api = AlmanacClient("http://almanac", transport=httpx.MockTransport(offline))
    with pytest.raises(ValueError, match="unavailable or timed out") as error:
        api.get("")
    assert "internal connection details" not in str(error.value)


@pytest.fixture
def live_catalogue(catalogue):
    service = make_server("127.0.0.1", 0, catalogue, threaded=True)
    thread = threading.Thread(target=service.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{service.server_port}"
    finally:
        service.shutdown()
        thread.join(timeout=5)
        service.server_close()


def test_lab_collector_reports_actual_calls(live_catalogue, tmp_path):
    evidence = asyncio.run(collect(live_catalogue))
    assert all(evidence["validation"].values())
    assert len(evidence["calls"]) == 6
    assert all(call["started_at"] and call["duration_ms"] >= 0 for call in evidence["calls"])
    assert evidence["human_review"]["decision"] == "pending"
    assert all(tool["inputSchema"] and tool["outputSchema"] for tool in evidence["tools"])
    root = Path(os.environ.get("MCP_EVIDENCE_DIR", str(tmp_path)))
    directory = root / evidence["run_id"]
    write_reports(evidence, directory)
    assert len(list(directory.iterdir())) == 5
    assert "not_run" in (directory / "tool-review.md").read_text()
    assert "PRIVATE_CHAT_SENTINEL" not in (directory / "evidence.json").read_text()
    with pytest.raises(FileExistsError):
        write_reports(evidence, directory)


def test_lab_collector_offline_captures_failure(tmp_path):
    evidence = asyncio.run(collect("http://127.0.0.1:1"))
    assert not all(evidence["validation"].values())
    assert all(call["is_error"] for call in evidence["calls"])
    write_reports(evidence, tmp_path / "offline")


def test_lab_collector_discovery_failure(monkeypatch):
    async def unavailable(url):
        raise RuntimeError("private internal error")

    monkeypatch.setattr("mcp_evidence._collect", unavailable)
    evidence = asyncio.run(collect("http://127.0.0.1:1"))
    assert evidence["validation"] == {"collection_completed": False}
    assert "private internal error" not in json.dumps(evidence)


def test_mcp_ui_gates_and_csrf(catalogue, monkeypatch):
    def unexpected(*args):
        pytest.fail("Disabled or invalid requests must not start a tool")

    monkeypatch.setattr("mcp_ui.run_tool", unexpected)
    client = catalogue.test_client()
    page = client.get("/tools")
    assert page.status_code == 200
    assert b"calculate_harvest" not in page.data
    assert (
        client.post("/tools/run", data={"enabled": "on", "tool": "search_catalogue"}).status_code
        == 400
    )
    catalogue.config["WTF_CSRF_ENABLED"] = False
    assert client.post("/tools/run", data={"tool": "search_catalogue"}).status_code == 403
    assert client.post("/tools/run", data={"enabled": "on", "tool": "read_file"}).status_code == 400
    assert (
        client.post(
            "/tools/run", data={"enabled": "on", "tool": "get_problem", "record_id": "bad"}
        ).status_code
        == 400
    )
    assert (
        client.post("/tools/run", data={"enabled": "on", "tool": "calculate_harvest"}).status_code
        == 400
    )
    catalogue.config["MCP_ENABLED"] = False
    assert b"disabled in the server" in client.get("/tools").data
    assert (
        client.post("/tools/run", data={"enabled": "on", "tool": "search_catalogue"}).status_code
        == 403
    )


def test_mcp_ui_actual_protocol_and_proxy(catalogue, live_catalogue):
    catalogue.config.update(WTF_CSRF_ENABLED=False, MCP_ALMANAC_BASE_URL=live_catalogue)
    client = catalogue.test_client()
    pest_id = Pest.query.filter_by(name="Aphids").one().id
    for inputs, expected in [
        ({"tool": "search_catalogue", "query": "Aphids"}, "Aphids"),
        ({"tool": "get_plant", "slug": "lettuce"}, "Includes estimated values"),
        ({"tool": "get_problem", "problem_kind": "pest", "record_id": pest_id}, "Aphids"),
    ]:
        response = client.post(
            "/tools/run",
            data={"enabled": "on", **inputs},
            headers={"X-Forwarded-Prefix": "/almanac"},
        )
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert expected in html and "View evidence" in html
        assert ">Copy response</button>" in html
        assert 'x-ref="evidence" tabindex="0"' in html
        assert "Copies the full evidence JSON." in html
        assert "PRIVATE_CHAT_SENTINEL" not in html
        if inputs["tool"] == "search_catalogue":
            assert f'href="/almanac/pests/{pest_id}"' in html
    response = client.post(
        "/tools/run", data={"enabled": "on", "tool": "get_plant", "slug": "missing"}
    )
    assert response.status_code == 502 and b"No answer returned" in response.data


def test_mcp_ui_escapes_evidence_and_connection_errors(catalogue, monkeypatch):
    catalogue.config["WTF_CSRF_ENABLED"] = False

    def malicious(*args):
        return {
            "calls": [
                {
                    "tool": "search_catalogue",
                    "is_error": False,
                    "duration_ms": 0,
                    "started_at": "now",
                    "output": {
                        "items": [],
                        "total": "<script>alert(1)</script>",
                        "next_offset": None,
                    },
                }
            ]
        }

    monkeypatch.setattr("mcp_ui.run_tool", malicious)
    client = catalogue.test_client()
    data = {"enabled": "on", "tool": "search_catalogue"}
    response = client.post("/tools/run", data=data)
    assert response.status_code == 200 and b"<script>alert(1)</script>" not in response.data

    def offline(*args):
        raise RuntimeError("private internal URL")

    monkeypatch.setattr("mcp_ui.run_tool", offline)
    response = client.post("/tools/run", data=data)
    assert response.status_code == 503 and b"private internal URL" not in response.data


def test_server_disable_flag_blocks_data(live_catalogue, monkeypatch):
    monkeypatch.setenv("MCP_ENABLED", "false")
    evidence = run_tool(live_catalogue, "get_plant", {"slug": "lettuce"})
    assert evidence["calls"][0]["is_error"]
    assert "disabled" in evidence["calls"][0]["message"]


def test_two_model_review_revision_and_failure():
    evidence = {
        "calls": [
            {"tool": "search_catalogue", "input": {}, "is_error": False, "output": {"total": 3}}
        ],
        "human_review": {"decision": "pending"},
    }
    models = []

    def fake(base, model, prompt, payload, schema):
        models.append(model)
        if model == "proposer":
            return {
                "summary": "The search returned three records.",
                "evidence_ids": [0],
                "limitations": ["No diagnosis."],
                "guide_checks": [],
            }
        return {
            "verdict": "revise" if len(models) == 2 else "approve",
            "reason": "Checked evidence.",
            "unsupported_claims": ["Recheck"] if len(models) == 2 else [],
            "next_test": "Search an unknown name; expect zero records.",
        }

    result = review_evidence(evidence, "http://localhost:11434", "proposer", "reviewer", fake)
    assert result["status"] == "model_approved"
    assert models == ["proposer", "reviewer", "proposer", "reviewer"]
    assert evidence["human_review"]["decision"] == "pending"

    def failed(*args):
        raise ValueError("private model response")

    assert review_evidence(evidence, "http://localhost", "p", "r", failed)["status"] == "failed"
    assert "private model response" not in json.dumps(evidence)


def test_model_review_rejects_fabricated_evidence_ids():
    evidence = {
        "calls": [{"tool": "search_catalogue", "input": {}, "is_error": False, "output": {}}]
    }

    def fake(*args):
        return {
            "summary": "Unsupported.",
            "evidence_ids": [999],
            "limitations": ["None."],
            "guide_checks": [],
        }

    result = review_evidence(evidence, "http://localhost", "p", "r", fake)
    assert result["status"] == "needs_revision"
    assert len(result["attempts"]) == 2
    with pytest.raises(ValueError, match="local Ollama"):
        generate("https://remote.example", "model", "prompt", {}, object)


def test_review_rejects_missing_guide_claim_before_model_approval():
    evidence = {
        "calls": [
            {
                "tool": "get_problem",
                "input": {},
                "is_error": False,
                "output": {"guide_available": True},
            }
        ]
    }

    def incorrect(*args):
        return {
            "summary": "The guide is unavailable.",
            "evidence_ids": [0],
            "limitations": ["Missing guide."],
            "guide_checks": [{"call_id": 0, "available": False}],
        }

    result = review_evidence(evidence, "http://localhost", "p", "r", incorrect)
    assert result["status"] == "needs_revision"
    assert all(
        "validation_error" in attempt and "review" not in attempt for attempt in result["attempts"]
    )


async def exercise_protocol(target):
    async with Client(target, read_timeout_seconds=10) as client:
        tools = (await client.list_tools()).tools
        assert {t.name for t in tools} == {
            "search_catalogue",
            "get_plant",
            "get_problem",
        }
        assert all(
            t.annotations.read_only_hint and not t.annotations.destructive_hint for t in tools
        )
        found = await client.call_tool("search_catalogue", {"query": "Aphids", "kind": "pest"})
        assert not found.is_error
        record_id = found.structured_content["items"][0]["id"]
        guide = await client.call_tool("get_problem", {"kind": "pest", "record_id": record_id})
        assert guide.structured_content["guide"]["sources"]
        plant = await client.call_tool("get_plant", {"slug": "lettuce"})
        assert "yield_qty" in plant.structured_content["record"]["estimated_fields"]
        for name, args in [
            ("search_catalogue", {"limit": 500}),
            ("get_plant", {"slug": "../../ai/history"}),
            ("get_problem", {"kind": "user", "record_id": 1}),
            ("get_problem", {"kind": "pest", "record_id": -1}),
            ("get_plant", {"slug": "no-such-plant"}),
            ("calculate_harvest", {"slug": "lettuce", "amount": 10, "unit": "head"}),
        ]:
            assert (await client.call_tool(name, args)).is_error
        resources = (await client.list_resources()).resources
        assert [str(r.uri) for r in resources] == ["almanac://about"]
        templates = (await client.list_resource_templates()).resource_templates
        assert len(templates) == 3
        for uri in ["almanac://plants/lettuce", f"almanac://pests/{record_id}"]:
            resource = await client.read_resource(uri)
            assert json.loads(resource.contents[0].text)["uri"] == uri
        disease = await client.call_tool("search_catalogue", {"kind": "disease"})
        disease_uri = disease.structured_content["items"][0]["uri"]
        disease_resource = await client.read_resource(disease_uri)
        assert json.loads(disease_resource.contents[0].text)["guide_available"]
        prompts = (await client.list_prompts()).prompts
        assert prompts[0].name == "investigate_plant_problem"
        prompt = await client.get_prompt(
            "investigate_plant_problem", {"plant": "lettuce", "observations": "curled leaves"}
        )
        assert "Do not claim a confirmed diagnosis" in prompt.messages[0].content.text


def test_mcp_stdio_against_live_almanac(live_catalogue, tmp_path):
    server_path = Path(__file__).resolve().parents[1] / "mcp_server.py"
    adapter_dir = tmp_path / "adapter"
    adapter_dir.mkdir()
    target = StdioServerParameters(
        command=sys.executable,
        args=[str(server_path)],
        env={"ALMANAC_BASE_URL": live_catalogue},
        cwd=adapter_dir,
    )
    asyncio.run(exercise_protocol(target))
    assert not list(adapter_dir.iterdir())


def test_mcp_streamable_http_against_live_almanac(live_catalogue, tmp_path):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    process = subprocess.Popen(
        [
            sys.executable,
            str(Path(__file__).resolve().parents[1] / "mcp_server.py"),
            "--transport",
            "streamable-http",
            "--port",
            str(port),
        ],
        env={**os.environ, "ALMANAC_BASE_URL": live_catalogue},
        cwd=tmp_path,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if process.poll() is not None:
                pytest.fail("MCP HTTP server exited before accepting connections")
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                    break
            except OSError:
                time.sleep(0.05)
        else:
            pytest.fail("MCP HTTP server did not start in 10 seconds")
        asyncio.run(exercise_protocol(f"http://127.0.0.1:{port}/mcp"))
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def test_mcp_reports_unavailable_service_without_fabricated_results():
    def offline(request):
        raise httpx.ConnectError("down")

    server = create_server(AlmanacClient("http://almanac", transport=httpx.MockTransport(offline)))

    async def check():
        async with Client(server) as client:
            response = await client.call_tool("search_catalogue", {"query": "tomato"})
            assert response.is_error
            assert "unavailable or timed out" in response.content[0].text

    asyncio.run(check())

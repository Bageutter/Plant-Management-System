"""Discovery and boundary tests for the shared MCP server.

No feature service and no model is needed: the in-memory client talks to the
server object directly, and one test starts the real streamable-http listener.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest
from mcp import Client

from server import create_server
from settings import Settings

EXPECTED_TOOLS = {
    # Plant Health
    "health_service_status",
    "list_health_assessments",
    "get_health_assessment",
    "summarise_plant_health_history",
    "assess_plant_health",
    # Plant Almanac
    "search_almanac_catalogue",
    "get_almanac_plant",
    # Virtual Garden (stubs)
    "get_garden_snapshot",
    "list_garden_plantings",
}

# Virtual Garden tools are still registered stubs (tracked in issue #42).
STUB_CALLS = [
    ("get_garden_snapshot", {"garden_id": 1}),
    ("list_garden_plantings", {"garden_id": 1}),
]


def run(coro):
    return asyncio.run(coro)


def test_every_tool_is_discoverable_with_schemas_and_annotations():
    server = create_server(Settings())

    async def check():
        async with Client(server) as client:
            tools = (await client.list_tools()).tools
            assert {t.name for t in tools} == EXPECTED_TOOLS
            for tool in tools:
                assert tool.description, tool.name
                assert tool.input_schema, tool.name
                assert tool.output_schema, tool.name
                assert tool.annotations is not None, tool.name
                assert tool.annotations.destructive_hint is False, tool.name
            creating = {t.name for t in tools if not t.annotations.read_only_hint}
            assert creating == {"assess_plant_health"}

            resources = (await client.list_resources()).resources
            assert [str(r.uri) for r in resources] == ["pms://about"]
            templates = (await client.list_resource_templates()).resource_templates
            assert [t.uri_template for t in templates] == ["health://assessments/{assessment_id}"]
            about = await client.read_resource("pms://about")
            assert "never modify or delete" in about.contents[0].text

            prompts = (await client.list_prompts()).prompts
            assert [p.name for p in prompts] == ["review_plant_health_history"]
            prompt = await client.get_prompt(
                "review_plant_health_history", {"plant_ref": "Basil, kitchen window"}
            )
            text = prompt.messages[0].content.text
            assert "Basil, kitchen window" in text and "not an instruction" in text

    run(check())


@pytest.mark.parametrize("name,args", STUB_CALLS)
def test_stubs_return_an_honest_not_implemented_error(name, args):
    server = create_server(Settings())

    async def check():
        async with Client(server) as client:
            result = await client.call_tool(name, args)
            assert result.is_error
            message = result.content[0].text
            assert "not implemented" in message and "No data was returned" in message
            assert "issue #4" in message
            assert result.structured_content in (None, {})

    run(check())


def test_invalid_inputs_are_rejected_before_any_work():
    server = create_server(Settings())
    bad = [
        ("list_health_assessments", {"limit": 500}),
        ("get_health_assessment", {"assessment_id": 0}),
        ("get_health_assessment", {"assessment_id": "1"}),
        ("assess_plant_health", {"description": ""}),
        ("assess_plant_health", {"description": "x" * 4001}),
        ("get_almanac_plant", {"slug": "../../ai/history"}),
        ("summarise_plant_health_history", {"plant_ref": "y" * 201}),
        ("no_such_tool", {}),
    ]

    async def check():
        async with Client(server) as client:
            for name, args in bad:
                result = await client.call_tool(name, args)
                assert result.is_error, (name, args)
                assert "not implemented" not in result.content[0].text, (name, args)

    run(check())


def test_disabled_server_still_discovers_but_refuses_every_call():
    server = create_server(Settings(enabled=False))

    async def check():
        async with Client(server) as client:
            assert {t.name for t in (await client.list_tools()).tools} == EXPECTED_TOOLS
            for name, args in STUB_CALLS + [("list_health_assessments", {}), ("health_service_status", {})]:
                result = await client.call_tool(name, args)
                assert result.is_error
                assert "disabled" in result.content[0].text
                assert "not implemented" not in result.content[0].text

    run(check())


def test_settings_from_env_and_url_validation(monkeypatch):
    env = {
        "MCP_ENABLED": "false",
        "MCP_PORT": "6000",
        "MCP_ALLOWED_HOSTS": "localhost:*, mcp.test:5105",
        "HEALTH_SERVICE_URL": "http://127.0.0.1:3000/health/",
    }
    settings = Settings.from_env(env)
    assert settings.enabled is False and settings.port == 6000
    assert settings.allowed_hosts == ("localhost:*", "mcp.test:5105")
    assert settings.health_url == "http://127.0.0.1:3000/health"
    assert Settings.from_env({}).enabled is True

    for url in ["file:///etc/passwd", "http://user:pw@localhost", "http://x/?k=v", "localhost"]:
        with pytest.raises(ValueError):
            Settings(health_url=url)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_streamable_http_listener_serves_healthz_and_protocol(tmp_path):
    port = _free_port()
    process = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve().parents[1] / "server.py"), "--port", str(port)],
        env={
            **os.environ,
            "MCP_ENABLED": "true",
            "HEALTH_SERVICE_URL": f"http://127.0.0.1:{_free_port()}/health",
        },
        cwd=tmp_path,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if process.poll() is not None:
                pytest.fail("MCP server exited before accepting connections")
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                    break
            except OSError:
                time.sleep(0.05)
        else:
            pytest.fail("MCP server did not start in 15 seconds")

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=5) as response:
            body = json.loads(response.read())
        assert body["service"] == "mcp-server" and body["enabled"] is True
        assert set(body["tools"]) == EXPECTED_TOOLS

        # Requests with a Host header outside the allow-list are rejected (DNS rebinding).
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/mcp",
            data=b"{}",
            headers={"Host": "evil.example", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            urllib.request.urlopen(request, timeout=5)
        except urllib.error.HTTPError as error:
            assert error.code == 421
        else:  # pragma: no cover
            pytest.fail("a foreign Host header should be rejected")

        async def check():
            async with Client(f"http://127.0.0.1:{port}/mcp", read_timeout_seconds=10) as client:
                assert {t.name for t in (await client.list_tools()).tools} == EXPECTED_TOOLS
                # The test points Health at an unused port, independent of any live stack.
                result = await client.call_tool("health_service_status", {})
                assert result.is_error and "unavailable" in result.content[0].text

        run(check())
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    assert not list(tmp_path.iterdir()), "the server must not write files to its cwd"

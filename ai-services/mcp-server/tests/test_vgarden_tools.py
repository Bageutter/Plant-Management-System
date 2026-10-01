"""Virtual Garden tools use vgarden's service-token-authenticated snapshot API —
unlike Almanac/Health, garden state is private per-owner, so every call must
carry the shared bearer token and never a tool-argument-supplied one."""

import asyncio

import httpx
import pytest
from mcp import Client

from server import create_server
from settings import Settings

SNAPSHOT = {
    "garden_id": 1,
    "name": "Backyard",
    "location_label": "Melbourne",
    "climate_zone": "temperate",
    "areas": [{"id": 1, "garden_id": 1, "parent_area_id": None, "name": "North bed",
               "area_type": "bed", "pos_x": 0.0, "pos_y": 0.0, "width": 2.0, "length": 3.0, "notes": None}],
    "containers": [],
    "plantings": [
        {
            "id": 1, "crop_name": "Tomato", "quantity": 3, "lifecycle_state": "growing",
            "growth_stage": "flowering", "planted_date": "2026-09-01",
            "expected_harvest_date": None, "location": "area: North bed",
        }
    ],
    "evidence_note": "Recorded garden state as entered by the owner.",
}
PLANTING_LIST = {"garden_id": 1, "items": SNAPSHOT["plantings"], "count": 1}


def call(handler, tool, arguments, *, enabled=True, token="dev-inter-service-secret-change-me"):
    server = create_server(
        Settings(enabled=enabled, vgarden_url="http://vgarden.test/vgarden", vgarden_service_token=token),
        transport=httpx.MockTransport(handler),
    )

    async def run():
        async with Client(server) as client:
            return await client.call_tool(tool, arguments)

    return asyncio.run(run())


def test_get_garden_snapshot_sends_the_shared_bearer_token():
    def handler(request):
        assert request.method == "GET"
        assert request.url.host == "vgarden.test"
        assert request.url.path == "/vgarden/gardens/1/snapshot"
        assert request.headers["authorization"] == "Bearer dev-inter-service-secret-change-me"
        return httpx.Response(200, json=SNAPSHOT)

    result = call(handler, "get_garden_snapshot", {"garden_id": 1})
    assert not result.is_error
    assert result.structured_content == SNAPSHOT


def test_list_garden_plantings_sends_the_shared_bearer_token():
    def handler(request):
        assert request.url.path == "/vgarden/gardens/1/plantings"
        assert request.headers["authorization"] == "Bearer dev-inter-service-secret-change-me"
        return httpx.Response(200, json=PLANTING_LIST)

    result = call(handler, "list_garden_plantings", {"garden_id": 1})
    assert not result.is_error
    assert result.structured_content == PLANTING_LIST


def test_configured_token_is_used_not_a_hardcoded_default():
    def handler(request):
        assert request.headers["authorization"] == "Bearer rotated-secret"
        return httpx.Response(200, json=SNAPSHOT)

    result = call(handler, "get_garden_snapshot", {"garden_id": 1}, token="rotated-secret")
    assert not result.is_error


@pytest.mark.parametrize("tool,args", [
    ("get_garden_snapshot", {"garden_id": 0}),
    ("get_garden_snapshot", {"garden_id": -1}),
    ("list_garden_plantings", {"garden_id": "x"}),
])
def test_invalid_inputs_never_reach_the_feature_api(tool, args):
    calls = []
    result = call(lambda request: calls.append(request), tool, args)
    assert result.is_error
    assert not calls


def test_disabled_tools_never_read_garden_state():
    calls = []
    result = call(lambda request: calls.append(request), "get_garden_snapshot", {"garden_id": 1}, enabled=False)
    assert result.is_error and "disabled" in result.content[0].text
    assert not calls


@pytest.mark.parametrize("response,message", [
    (httpx.Response(401, json={"error": "unauthorized"}), "401"),
    (httpx.Response(404, json={"error": "garden not found"}), "garden not found"),
    (httpx.Response(200, text="not JSON"), "non-JSON"),
    (httpx.Response(200, json={"unrelated": "data"}), "unexpected snapshot"),
])
def test_api_failures_are_tool_errors_without_invented_results(response, message):
    result = call(lambda request: response, "get_garden_snapshot", {"garden_id": 1})
    assert result.is_error and message in result.content[0].text
    assert not result.structured_content


def test_unavailable_service_is_reported():
    def unavailable(request):
        raise httpx.ConnectError("offline", request=request)

    result = call(unavailable, "get_garden_snapshot", {"garden_id": 1})
    assert result.is_error and "unavailable" in result.content[0].text
    assert not result.structured_content

"""Almanac tools use only the public catalogue API and preserve its evidence."""

import asyncio

import httpx
import pytest
from mcp import Client

from server import create_server
from settings import Settings

PLANT = {
    "kind": "plant", "id": 1, "key": "tomato", "name": "Tomato",
    "uri": "almanac://plants/tomato", "path": "/almanac/plants/tomato",
}
DISEASE = {
    "kind": "disease", "id": 2, "key": "2", "name": "Powdery mildew",
    "uri": "almanac://diseases/2", "path": "/almanac/diseases/2",
}


def call(handler, tool, arguments, *, enabled=True):
    server = create_server(
        Settings(enabled=enabled, almanac_url="http://catalogue.test/almanac"),
        transport=httpx.MockTransport(handler),
    )

    async def run():
        async with Client(server) as client:
            return await client.call_tool(tool, arguments)

    return asyncio.run(run())


def test_search_forwards_filters_to_fixed_read_only_endpoint():
    def handler(request):
        assert request.method == "GET"
        assert request.url.host == "catalogue.test"
        assert request.url.path == "/almanac/api/catalogue"
        assert dict(request.url.params) == {"q": "mildew", "kind": "disease", "limit": "3"}
        return httpx.Response(200, json={
            "items": [DISEASE], "total": 1, "limit": 3, "offset": 0, "next_offset": None,
        })

    result = call(handler, "search_almanac_catalogue", {
        "query": "mildew", "kind": "disease", "limit": 3,
    })
    assert not result.is_error
    assert result.structured_content["items"] == [DISEASE]


def test_plant_detail_keeps_missing_fields_linked_problems_and_evidence():
    payload = {
        **PLANT, "record": {"common_name": "Tomato", "yield_qty": None},
        "pests": [], "diseases": [DISEASE],
        "evidence_note": "Catalogue associations are not confirmed diagnoses.",
    }

    def handler(request):
        assert request.method == "GET"
        assert str(request.url) == "http://catalogue.test/almanac/api/catalogue/plant/tomato"
        return httpx.Response(200, json=payload)

    result = call(handler, "get_almanac_plant", {"slug": "tomato"})
    assert not result.is_error
    assert result.structured_content == payload


@pytest.mark.parametrize("tool,args", [
    ("search_almanac_catalogue", {"query": "x" * 121}),
    ("search_almanac_catalogue", {"kind": "history"}),
    ("search_almanac_catalogue", {"limit": 51}),
    ("get_almanac_plant", {"slug": "../ai/history"}),
])
def test_invalid_inputs_never_reach_the_feature_api(tool, args):
    calls = []
    result = call(lambda request: calls.append(request), tool, args)
    assert result.is_error
    assert not calls


@pytest.mark.parametrize("tool,args", [
    ("search_almanac_catalogue", {}),
    ("get_almanac_plant", {"slug": "tomato"}),
])
def test_disabled_tools_never_read_catalogue(tool, args):
    calls = []
    result = call(lambda request: calls.append(request), tool, args, enabled=False)
    assert result.is_error and "disabled" in result.content[0].text
    assert not calls


@pytest.mark.parametrize("response,message", [
    (httpx.Response(404, json={"error": "Plant not found"}), "Plant not found"),
    (httpx.Response(200, text="not JSON"), "non-JSON"),
    (httpx.Response(200, json={"unrelated": "data"}), "unexpected plant result"),
])
def test_api_failures_are_tool_errors_without_invented_results(response, message):
    result = call(lambda request: response, "get_almanac_plant", {"slug": "tomato"})
    assert result.is_error and message in result.content[0].text
    assert not result.structured_content


def test_unavailable_service_is_reported():
    def unavailable(request):
        raise httpx.ConnectError("offline", request=request)

    result = call(unavailable, "search_almanac_catalogue", {})
    assert result.is_error and "unavailable" in result.content[0].text
    assert not result.structured_content

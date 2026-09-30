"""Plant Health tools against a fake health API (httpx MockTransport).

The fake mirrors the real service's public JSON contract closely enough to prove
the mapping, the filters, the aggregate computation and every error path — with
no real service and no model.
"""

from __future__ import annotations

import asyncio
import json
from urllib.parse import parse_qs

import httpx
import pytest
from mcp import Client

from server import create_server
from settings import Settings

RECORDS = [
    {
        "id": 3,
        "plant_ref": "Tomato, back bed",
        "description": "Lower leaves yellow, soil stays wet.",
        "has_image": False,
        "image_mime": None,
        "model": "qwen2.5vl:3b",
        "status": "at_risk",
        "health_score": 42,
        "score_band": "At risk — will worsen without action",
        "confidence": "medium",
        "confidence_reason": "Description covers watering but no photo.",
        "duration_ms": 6100,
        "plant_identification": "Tomato (Solanum lycopersicum)",
        "summary": "Yellowing with constantly wet soil suggests overwatering.",
        "issues": [
            {"name": "Overwatering", "severity": "high", "evidence": "Soil stays wet"},
            {"name": "Nitrogen deficiency", "severity": "low", "evidence": "Lower-leaf yellowing"},
        ],
        "recommendations": [
            {"action": "Reduce watering", "priority": "high", "details": "Let top 3cm dry."}
        ],
        "missing_information": ["A photo of the leaves"],
        "created_at": "2026-09-20T05:30:00+00:00",
    },
    {
        "id": 2,
        "plant_ref": "Tomato, back bed",
        "description": "Planted 4 weeks ago, looks fine.",
        "has_image": True,
        "image_mime": "image/jpeg",
        "model": "qwen2.5vl:3b",
        "status": "healthy",
        "health_score": 88,
        "score_band": "Thriving — routine care only",
        "confidence": "high",
        "confidence_reason": "Sharp photo, healthy foliage.",
        "duration_ms": 5000,
        "plant_identification": "Tomato",
        "summary": "Vigorous growth, no visible issues.",
        "issues": [],
        "recommendations": [],
        "missing_information": [],
        "created_at": "2026-09-10T05:30:00+00:00",
    },
    {
        "id": 1,
        "plant_ref": "Basil, kitchen window",
        "description": None,
        "has_image": True,
        "image_mime": "image/jpeg",
        "model": "qwen2.5vl:3b",
        "status": "unhealthy",
        "health_score": 20,
        "score_band": "Severe decline, dying, or dead",
        "confidence": "medium",
        "confidence_reason": "Photo shows widespread damage.",
        "duration_ms": 4000,
        "plant_identification": "Basil",
        "summary": "Extensive leaf damage consistent with pests.",
        "issues": [{"name": "overwatering", "severity": "medium", "evidence": "Wilting"}],
        "recommendations": [{"action": "Inspect undersides", "priority": "medium", "details": ""}],
        "missing_information": [],
        "created_at": "2026-09-01T05:30:00+00:00",
    },
]


class FakeHealthAPI:
    """Just enough of the health service's public API, served over MockTransport."""

    def __init__(self, ai_up: bool = True):
        self.ai_up = ai_up
        self.calls: list[httpx.Request] = []
        self.records = [dict(r) for r in RECORDS]

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        path = request.url.path
        if path == "/health/healthz":
            body = {
                "service": "health-monitoring-service",
                "status": "ok" if self.ai_up else "degraded",
                "ai": {"url": "http://ollama:11434", "model": "qwen2.5vl:3b", "reachable": self.ai_up},
            }
            return httpx.Response(200 if self.ai_up else 503, json=body)
        if path == "/health/plant-health-records/assessments" and request.method == "GET":
            params = parse_qs(request.url.query.decode())
            items = self.records
            if "plant_ref" in params:
                items = [r for r in items if r["plant_ref"] == params["plant_ref"][0]]
            if "status" in params:
                items = [r for r in items if r["status"] == params["status"][0]]
            limit = int(params.get("limit", ["50"])[0])
            return httpx.Response(200, json=items[:limit])
        if path == "/health/plant-health-records/assessments" and request.method == "POST":
            if not self.ai_up:
                return httpx.Response(503, json={"error": "Could not reach the local AI instance"})
            payload = json.loads(request.content)
            if not payload.get("description"):
                return httpx.Response(400, json={"error": "Provide an image, a text description, or both."})
            record = {**RECORDS[0], "id": 4, **payload, "status": "healthy", "health_score": 80}
            self.records.insert(0, record)
            return httpx.Response(201, json=record)
        if path.startswith("/health/plant-health-records/assessments/"):
            record_id = path.rsplit("/", 1)[-1]
            for record in self.records:
                if str(record["id"]) == record_id:
                    return httpx.Response(200, json=record)
            return httpx.Response(404, json={"error": "assessment not found"})
        return httpx.Response(500, text="unexpected path")


@pytest.fixture
def fake():
    return FakeHealthAPI()


def make_server(fake: FakeHealthAPI, **settings):
    return create_server(
        Settings(health_url="http://127.0.0.1:3000/health", **settings),
        transport=httpx.MockTransport(fake.handler),
    )


def call(server, name, args):
    async def go():
        async with Client(server) as client:
            return await client.call_tool(name, args)

    return asyncio.run(go())


def test_status_tool_reports_ok_and_degraded(fake):
    server = make_server(fake)
    result = call(server, "health_service_status", {})
    assert not result.is_error
    assert result.structured_content["status"] == "ok"
    assert result.structured_content["ai_reachable"] is True
    assert result.structured_content["model"] == "qwen2.5vl:3b"

    fake.ai_up = False
    degraded = call(server, "health_service_status", {})
    assert not degraded.is_error and degraded.structured_content["status"] == "degraded"
    assert degraded.structured_content["ai_reachable"] is False


def test_list_tool_maps_records_filters_and_never_includes_images(fake):
    server = make_server(fake)
    result = call(server, "list_health_assessments", {"limit": 5})
    assert not result.is_error
    body = result.structured_content
    assert body["count"] == 3 and [i["id"] for i in body["items"]] == [3, 2, 1]
    first = body["items"][0]
    assert first["url"] == "http://127.0.0.1:3000/health/plant-health-records/3"
    assert first["status"] == "at_risk" and first["health_score"] == 42
    assert "image_data" not in first and "description" not in first
    assert "advisory" in body["evidence_note"]

    filtered = call(
        server,
        "list_health_assessments",
        {"plant_ref": "Tomato, back bed", "status": "healthy", "limit": 5},
    )
    assert [i["id"] for i in filtered.structured_content["items"]] == [2]
    sent = parse_qs(fake.calls[-1].url.query.decode())
    assert sent == {"limit": ["5"], "plant_ref": ["Tomato, back bed"], "status": ["healthy"]}

    empty = call(server, "list_health_assessments", {"plant_ref": "Nothing planted here"})
    assert not empty.is_error and empty.structured_content["items"] == []


def test_get_tool_returns_full_record_or_a_not_found_error(fake):
    server = make_server(fake)
    result = call(server, "get_health_assessment", {"assessment_id": 3})
    assert not result.is_error
    body = result.structured_content
    assert body["issues"][0]["name"] == "Overwatering"
    assert body["recommendations"][0]["priority"] == "high"
    assert body["confidence_reason"].startswith("Description covers")

    missing = call(server, "get_health_assessment", {"assessment_id": 999})
    assert missing.is_error and "not found" in missing.content[0].text


def test_history_summary_aggregates_in_code(fake):
    server = make_server(fake)
    result = call(server, "summarise_plant_health_history", {"plant_ref": "Tomato, back bed"})
    assert not result.is_error
    body = result.structured_content
    assert body["assessments"] == 2
    assert body["status_counts"] == {"healthy": 1, "at_risk": 1, "unhealthy": 0, "unknown": 0}
    assert body["latest"]["id"] == 3
    # Oldest first so the trend reads chronologically.
    assert [(p["assessment_id"], p["health_score"]) for p in body["score_trend"]] == [(2, 88), (3, 42)]
    assert body["recurring_issues"][0] == {
        "name": "Overwatering",
        "occurrences": 1,
        "worst_severity": "high",
    }

    none = call(server, "summarise_plant_health_history", {"plant_ref": "Unknown plant"})
    assert none.structured_content["assessments"] == 0 and none.structured_content["latest"] is None


def test_recurring_issues_merge_case_insensitively_and_keep_worst_severity():
    fake = FakeHealthAPI()
    for record in fake.records:
        record["plant_ref"] = "Same plant"
    server = make_server(fake)
    body = call(
        server, "summarise_plant_health_history", {"plant_ref": "Same plant"}
    ).structured_content
    top = body["recurring_issues"][0]
    assert top["name"] == "Overwatering" and top["occurrences"] == 2
    assert top["worst_severity"] == "high"


def test_assess_tool_posts_text_only_and_surfaces_ai_outage(fake):
    server = make_server(fake)
    result = call(
        server,
        "assess_plant_health",
        {"description": "Leaves curling, brown edges.", "plant_ref": "Chilli"},
    )
    assert not result.is_error
    posted = json.loads(fake.calls[-1].content)
    assert posted == {"description": "Leaves curling, brown edges.", "plant_ref": "Chilli"}
    assert "image_base64" not in posted
    assert result.structured_content["id"] == 4

    fake.ai_up = False
    outage = call(server, "assess_plant_health", {"description": "Leaves curling."})
    assert outage.is_error and "local AI" in outage.content[0].text


def test_resource_reads_one_record_and_rejects_bad_ids(fake):
    server = make_server(fake)

    async def go():
        async with Client(server) as client:
            resource = await client.read_resource("health://assessments/2")
            body = json.loads(resource.contents[0].text)
            assert body["id"] == 2 and body["status"] == "healthy"
            for uri in ["health://assessments/0", "health://assessments/abc"]:
                with pytest.raises(Exception):
                    await client.read_resource(uri)

    asyncio.run(go())


def test_service_down_is_reported_without_internal_details():
    def offline(request):
        raise httpx.ConnectError("secret internal hostname")

    server = create_server(
        Settings(health_url="http://127.0.0.1:3000/health"), transport=httpx.MockTransport(offline)
    )
    result = call(server, "list_health_assessments", {})
    assert result.is_error
    text = result.content[0].text
    assert "unavailable or timed out" in text and "secret internal hostname" not in text


def test_redirects_are_never_followed():
    seen = []

    def redirecting(request):
        seen.append(request)
        return httpx.Response(302, headers={"location": "http://other/private"})

    server = create_server(
        Settings(health_url="http://127.0.0.1:3000/health"),
        transport=httpx.MockTransport(redirecting),
    )
    result = call(server, "get_health_assessment", {"assessment_id": 1})
    assert result.is_error and "HTTP 302" in result.content[0].text
    assert len(seen) == 1


def test_disabled_flag_blocks_every_health_tool_before_any_request(fake):
    server = make_server(fake, enabled=False)
    result = call(server, "list_health_assessments", {})
    assert result.is_error and "disabled" in result.content[0].text
    assert fake.calls == []

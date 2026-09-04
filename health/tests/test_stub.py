"""Showcase fast-mode: OllamaClient(stub=True) returns canned assessments with
no network call, in the same shape as the real vision model."""

from ai import OllamaClient


def _client():
    return OllamaClient(base_url="http://unused", model="qwen2.5vl:3b", stub=True)


def test_stub_assess_flags_a_described_problem():
    result = _client().assess(description="Lower leaves are yellowing and curling.")
    assert result["status"] == "at_risk"
    assert 0 <= result["health_score"] <= 100
    assert result["issues"] and result["recommendations"]
    assert result["duration_ms"] > 0


def test_stub_assess_reads_a_healthy_description_as_healthy():
    result = _client().assess(description="Strong new growth, deep green leaves, no problems.")
    assert result["status"] == "healthy"
    assert result["issues"] == []


def test_stub_assess_stream_emits_progress_then_one_result():
    events = list(_client().assess_stream(description="brown spots on the leaves"))
    assert events[-1]["type"] == "result"
    assert all(e["type"] == "progress" for e in events[:-1])
    assert events[-1]["result"]["status"] == "at_risk"


def test_stub_still_requires_some_input():
    events = list(_client().assess_stream())
    assert events == [{"type": "error", "message": "An image or a text description is required."}]

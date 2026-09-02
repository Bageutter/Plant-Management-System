import io
import json

import pytest

import ai
from ai import AIUnavailableError, OllamaGardenAI


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _fake_urlopen(script):
    """script: list of (url_substring, payload_dict). Matched in order of calls."""
    calls = []

    def fake(url_or_request, timeout=None):
        url = getattr(url_or_request, "full_url", url_or_request)
        calls.append(url)
        for substr, payload in script:
            if substr in url:
                return FakeResponse(json.dumps(payload).encode("utf-8"))
        raise AssertionError(f"unexpected URL: {url}")

    fake.calls = calls
    return fake


def test_ensure_model_raises_when_ollama_unreachable(monkeypatch):
    def boom(*a, **k):
        raise ai.error.URLError("connection refused")

    monkeypatch.setattr(ai.request, "urlopen", boom)
    with pytest.raises(AIUnavailableError, match="Cannot reach Ollama"):
        OllamaGardenAI("http://ollama:11434", "qwen3:4b-instruct").ask("hi", {}, [])


def test_ensure_model_raises_when_model_missing_and_no_auto_pull(monkeypatch):
    monkeypatch.setattr(
        ai.request,
        "urlopen",
        _fake_urlopen([("/api/tags", {"models": [{"name": "llama3.1:8b"}]})]),
    )
    with pytest.raises(AIUnavailableError, match="not on the Ollama instance"):
        OllamaGardenAI("http://ollama:11434", "qwen3:4b-instruct", auto_pull=False).ask("hi", {}, [])


def test_auto_pull_then_answers(monkeypatch):
    monkeypatch.setattr(
        ai.request,
        "urlopen",
        _fake_urlopen(
            [
                ("/api/tags", {"models": []}),
                ("/api/pull", {"status": "success"}),
                ("/api/chat", {"message": {"content": json.dumps({"answer": "Hello from the garden."})}}),
            ]
        ),
    )
    client = OllamaGardenAI("http://ollama:11434", "qwen3:4b-instruct", auto_pull=True)

    result = client.ask("hi", {"name": "G"}, [])

    assert result == {"answer": "Hello from the garden."}

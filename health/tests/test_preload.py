"""Startup model preload: warms the model without ever blocking or failing startup."""

from __future__ import annotations

import threading

import pytest
from flask import Flask, jsonify, request
from werkzeug.serving import make_server

from ai import AIUnavailableError, OllamaClient
from conftest import TestConfig


class FakeOllamaServer:
    """Just enough of Ollama's HTTP API to observe a preload: /api/tags + /api/chat."""

    def __init__(self, models=("qwen2.5vl:3b",)):
        self.models = list(models)
        self.chats = []
        self.pulls = []
        app = Flask("fake-ollama")

        @app.route("/api/tags")
        def tags():
            return jsonify({"models": [{"name": m} for m in self.models]})

        @app.route("/api/pull", methods=["POST"])
        def pull():
            self.pulls.append(request.get_json())
            self.models.append(request.get_json()["model"])
            return jsonify({"status": "success"})

        @app.route("/api/chat", methods=["POST"])
        def chat():
            payload = request.get_json()
            self.chats.append(payload)
            # Ollama answers an empty-messages request by loading the model only.
            return jsonify({"model": payload["model"], "done": True, "done_reason": "load"})

        self.server = make_server("127.0.0.1", 0, app, threaded=True)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()


@pytest.fixture
def ollama():
    fake = FakeOllamaServer()
    yield fake
    fake.stop()


def test_preload_asks_ollama_to_load_the_model_and_keep_it_resident(ollama):
    client = OllamaClient(ollama.url, "qwen2.5vl:3b", keep_alive="30m", auto_pull=False)
    assert client.preload_state["status"] == "not_started"

    client.preload()

    assert ollama.chats == [{"model": "qwen2.5vl:3b", "messages": [], "keep_alive": "30m"}]
    assert ollama.pulls == []  # the model was already present
    assert client.preload_state["status"] == "loaded"
    assert client.preload_state["duration_ms"] >= 0 and client.preload_state["loaded_at"]


def test_preload_pulls_a_missing_model_first_when_allowed(ollama):
    ollama.models = ["something-else"]
    client = OllamaClient(ollama.url, "qwen2.5vl:3b", auto_pull=True)
    client.preload()
    assert [p["model"] for p in ollama.pulls] == ["qwen2.5vl:3b"]
    assert client.preload_state["status"] == "loaded"

    ollama.models = ["something-else"]
    strict = OllamaClient(ollama.url, "other-model", auto_pull=False)
    with pytest.raises(AIUnavailableError, match="not available"):
        strict.preload()


def test_start_preload_runs_in_the_background_and_retries_until_it_succeeds(ollama):
    client = OllamaClient(ollama.url, "qwen2.5vl:3b", auto_pull=False)
    # Point at a closed port first, then "bring Ollama up" between attempts.
    real_url = client.base_url
    client.base_url = "http://127.0.0.1:1"
    flips = {"done": False}
    original_preload = client.preload

    def flaky_preload():
        if not flips["done"]:
            flips["done"] = True
            raise AIUnavailableError("Ollama still starting")
        client.base_url = real_url
        original_preload()

    client.preload = flaky_preload
    thread = client.start_preload(retries=3, delay=0)
    thread.join(timeout=10)

    assert not thread.is_alive()
    assert client.preload_state["status"] == "loaded"
    assert client.preload_state["attempts"] == 2
    assert len(ollama.chats) == 1


def test_start_preload_gives_up_quietly_after_the_retry_budget():
    client = OllamaClient("http://127.0.0.1:1", "qwen2.5vl:3b", auto_pull=False, timeout=1)
    thread = client.start_preload(retries=2, delay=0)
    thread.join(timeout=15)

    assert not thread.is_alive()
    state = client.preload_state
    assert state["status"] == "failed" and state["attempts"] == 2
    assert "first request will load it" in state["detail"]


def test_create_app_starts_the_preload_only_when_configured(tmp_path, monkeypatch):
    from app import create_app

    started = []
    monkeypatch.setattr(OllamaClient, "start_preload", lambda self, **kw: started.append(kw))

    class Off(TestConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'off.db'}"
        OLLAMA_PRELOAD = False

    create_app(Off)
    assert started == []

    class On(TestConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'on.db'}"
        OLLAMA_PRELOAD = True
        OLLAMA_PRELOAD_RETRIES = 3
        OLLAMA_PRELOAD_RETRY_SECONDS = 0.5

    create_app(On)
    assert started == [{"retries": 3, "delay": 0.5}]


def test_healthz_reports_the_preload_state(client, fake_ai):
    body = client.get("/healthz").get_json()
    assert body["ai"]["preload"]["status"] == "loaded"
    fake_ai.preload_state = {"status": "retrying", "attempts": 2, "detail": "Ollama still starting"}
    assert client.get("/healthz").get_json()["ai"]["preload"]["status"] == "retrying"

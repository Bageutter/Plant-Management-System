"""Shared fixtures for the health service tests.

Every test runs against a temporary SQLite database and a fake Ollama client, so
no model is needed. The MCP fixture wires the *real* shared MCP server in-process
(``ai-services/mcp-server``) and routes its outbound HTTP calls back into this very
Flask app through an httpx WSGI transport, so the frontend → backend → MCP server →
health API loop is exercised end to end without sockets.
"""

from __future__ import annotations

import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_MCP_SERVER = os.path.join(_HERE, "..", "ai-services", "mcp-server")
for path in (_HERE, _MCP_SERVER):
    if os.path.isdir(path) and path not in sys.path:
        sys.path.insert(0, path)


class FakeOllama:
    """Stands in for ai.OllamaClient: instant, deterministic, no network."""

    def __init__(self):
        self.base_url = "http://fake-ollama"
        self.model = "fake-vision-model"
        self.reachable = True
        self.calls = []
        self.preload_state = {"status": "loaded", "attempts": 1, "detail": "fake"}

    def ping(self):
        return self.reachable

    def _result(self, description, plant_ref):
        return {
            "status": "at_risk",
            "health_score": 45,
            "score_band": "At risk — will worsen without action",
            "confidence": "medium",
            "confidence_reason": "Written description only, no photo.",
            "plant_identification": "Tomato (Solanum lycopersicum)",
            "summary": f"Assessment of {plant_ref or 'the plant'}: {(description or '')[:60]}",
            "issues": [{"name": "Overwatering", "severity": "medium", "evidence": "Soil stays wet"}],
            "recommendations": [
                {"action": "Reduce watering", "priority": "high", "details": "Let the top 3cm dry."}
            ],
            "missing_information": ["A photo of the affected leaves"],
            "duration_ms": 12,
        }

    def assess(self, description=None, image_b64=None, plant_ref=None):
        from ai import AIUnavailableError

        self.calls.append({"description": description, "plant_ref": plant_ref, "image": bool(image_b64)})
        if not self.reachable:
            raise AIUnavailableError("Could not reach the local AI instance at http://fake-ollama")
        return self._result(description, plant_ref)

    def assess_stream(self, description=None, image_b64=None, plant_ref=None):
        yield {"type": "progress", "field": "Writing the summary", "summary": "…", "chars": 1, "elapsed_ms": 1}
        yield {"type": "result", "result": self._result(description, plant_ref)}


class TestConfig:
    TESTING = True
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    AUTH_PUBLIC_URL = "http://auth.test"
    HEALTH_PUBLIC_URL = "http://localhost:3000/health/plant-health-records/"
    ALMANAC_PUBLIC_URL = "http://localhost:3000/almanac/"
    OLLAMA_URL = "http://fake-ollama"
    OLLAMA_MODEL = "fake-vision-model"
    OLLAMA_TIMEOUT = 1
    OLLAMA_AUTO_PULL = False
    OLLAMA_PULL_TIMEOUT = 1
    OLLAMA_KEEP_ALIVE = "1m"
    OLLAMA_NUM_PREDICT = 10
    OLLAMA_NUM_CTX = 512
    OLLAMA_PRELOAD = False  # no background thread hitting a fake URL during tests
    MAX_CONTENT_LENGTH = 1024 * 1024
    ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
    IMAGE_MAX_EDGE = 64
    MCP_ENABLED = True
    MCP_SERVER_URL = "http://127.0.0.1:1/mcp"  # replaced per test
    RAG_ENABLED = True
    RAG_SERVER_URL = "http://127.0.0.1:1"  # replaced per test
    INTEGRATION_TIMEOUT = 5


@pytest.fixture
def app(tmp_path):
    from app import create_app

    class Config(TestConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{os.path.join(tmp_path, 'health.db')}"

    application = create_app(Config)
    application.extensions["ollama"] = FakeOllama()
    return application


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def fake_ai(app):
    return app.extensions["ollama"]


def make_assessment(client, plant_ref="Tomato, back bed", description="Lower leaves yellow, soil wet."):
    response = client.post(
        "/plant-health-records/assessments",
        json={"plant_ref": plant_ref, "description": description},
    )
    assert response.status_code == 201, response.get_data(as_text=True)
    return response.get_json()

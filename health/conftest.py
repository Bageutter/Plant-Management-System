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
import tempfile

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_MCP_SERVER = os.path.join(_HERE, "..", "ai-services", "mcp-server")
_SHARED = os.path.join(_HERE, "..", "shared")  # ai_loop.py, as app.py does at runtime
for path in (_HERE, _MCP_SERVER, _SHARED):
    if os.path.isdir(path) and path not in sys.path:
        sys.path.insert(0, path)


class FakeOllama:
    """Stands in for ai.OllamaClient: instant, deterministic, no network."""

    def __init__(self):
        self.base_url = "http://fake-ollama"
        self.model = "fake-vision-model"
        self.reachable = True
        self.calls = []
        # Per-call overrides merged into the result (the last entry repeats), so a
        # test can make the first draft inconsistent and the next one fine.
        self.script = []
        self.preload_state = {"status": "loaded", "attempts": 1, "detail": "fake"}

    def ping(self):
        return self.reachable

    def _result(self, description, plant_ref, call_index=0):
        result = self._base_result(description, plant_ref)
        if self.script:
            result.update(self.script[min(call_index, len(self.script) - 1)])
        return result

    def _base_result(self, description, plant_ref):
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

    def _record(self, description, image_b64, plant_ref, feedback, history):
        self.calls.append(
            {
                "description": description,
                "plant_ref": plant_ref,
                "image": bool(image_b64),
                "feedback": feedback,
                "history": list(history or []),
            }
        )
        return len(self.calls) - 1

    def assess(self, description=None, image_b64=None, plant_ref=None, feedback=None, history=None):
        from ai import AIUnavailableError

        index = self._record(description, image_b64, plant_ref, feedback, history)
        if not self.reachable:
            raise AIUnavailableError("Could not reach the local AI instance at http://fake-ollama")
        return self._result(description, plant_ref, index)

    def assess_stream(self, description=None, image_b64=None, plant_ref=None, feedback=None, history=None):
        index = self._record(description, image_b64, plant_ref, feedback, history)
        if not self.reachable:
            yield {"type": "error", "message": "Could not reach the local AI instance at http://fake-ollama"}
            return
        yield {"type": "progress", "field": "Writing the summary", "summary": "…", "chars": 1, "elapsed_ms": 1}
        yield {"type": "result", "result": self._result(description, plant_ref, index)}


class FakeReviewer:
    """Stand-in for ai_loop.Reviewer with the health prompt. Emits verdicts from
    `script` (repeating the last one) so the loop is driven deterministically."""

    model = "fake-reviewer"

    def __init__(self, script=None):
        self.script = list(script or ["approved"])
        self.calls = []
        self.fail = False

    def review(self, question, grounding, draft):
        if self.fail:
            raise RuntimeError("reviewer offline")
        self.calls.append({"question": question, "grounding": grounding, "draft": draft})
        verdict = self.script[min(len(self.calls) - 1, len(self.script) - 1)]
        if verdict == "approved":
            return {"verdict": "approved", "issues": [], "guidance": ""}
        return {
            "verdict": "revise",
            "issues": ["draft not grounded"],
            "guidance": f"fix iteration {len(self.calls)}",
        }


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
    # No review model -> build_reviewer() returns None; the autouse fixture below
    # injects a FakeReviewer instead.
    OLLAMA_REVIEW_MODEL = None
    AI_LOOP_MAX_ITERATIONS = 2
    AI_LOOP_LOG_DIR = os.path.join(tempfile.gettempdir(), "health-ai-loop-test-logs")
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
        AI_LOOP_LOG_DIR = os.path.join(tmp_path, "ai-loop-logs")

    application = create_app(Config)
    application.extensions["ollama"] = FakeOllama()
    return application


@pytest.fixture(autouse=True)
def ai_loop_reviewer(app):
    """Every test gets a reviewer that approves on the first pass (1 iteration,
    verdict 'approved'). Override `.script` for revision tests."""

    fake = FakeReviewer()
    app.extensions["ai_loop_reviewer"] = fake
    return fake


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

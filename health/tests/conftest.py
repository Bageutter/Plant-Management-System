"""`python -m pytest` from health/ puts the service dir on sys.path so tests can
`import app`, `import routes`, etc. as top-level modules."""

import os
import sys

import pytest

_SHARED = os.path.join(os.path.dirname(__file__), "..", "..", "shared")
if os.path.isdir(_SHARED) and _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)

from app import create_app  # noqa: E402
from config import Config  # noqa: E402


class FakeOllamaClient:
    """Stand-in for ai.OllamaClient — no network, deterministic result."""

    def __init__(self):
        self.model = "fake-model"
        self.base_url = "http://ollama.test:11434"
        self.result = {
            "status": "at_risk",
            "health_score": 55,
            "score_band": "At risk — will worsen without action",
            "confidence": "medium",
            "confidence_reason": "text description only, no photo",
            "plant_identification": "Tomato",
            "summary": "Some lower-leaf yellowing; upper growth healthy.",
            "issues": [{"name": "Chlorosis", "severity": "medium", "evidence": "yellow lower leaves"}],
            "recommendations": [{"action": "Reduce watering", "priority": "high", "details": "let soil dry"}],
            "missing_information": ["A close-up photo"],
            "duration_ms": 10,
        }

    def ping(self):
        return True

    def assess(self, description=None, image_b64=None, plant_ref=None):
        return dict(self.result)


class FakeChatAI:
    """Stand-in drafter for the 'discuss this assessment' loop."""

    def __init__(self):
        self.calls = []

    def draft(self, question, grounding, feedback=None):
        self.calls.append({"question": question, "grounding": grounding, "feedback": feedback})
        return f"About '{question}': based on the assessment, ease off watering first."


class FakeReviewer:
    def __init__(self, script=None):
        self.script = list(script or ["approved"])
        self.calls = []

    def review(self, question, grounding, draft):
        self.calls.append(draft)
        verdict = self.script[min(len(self.calls) - 1, len(self.script) - 1)]
        if verdict == "approved":
            return {"verdict": "approved", "issues": [], "guidance": ""}
        return {"verdict": "revise", "issues": ["ungrounded"], "guidance": f"fix {len(self.calls)}"}


@pytest.fixture
def app(tmp_path):
    class _Config(Config):
        TESTING = True
        SEED_DEMO_DATA = False
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'health.db'}"
        AI_LOOP_LOG_DIR = str(tmp_path / "ai-loop-logs")
        AI_LOOP_MAX_ITERATIONS = 2

    application = create_app(_Config)
    application.extensions["ollama"] = FakeOllamaClient()
    application.extensions["health_chat_ai"] = FakeChatAI()
    application.extensions["ai_loop_reviewer"] = FakeReviewer()
    return application


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def seeded(app):
    """Load the demo assessments into the test database; return how many."""
    from models import Assessment
    from seed_data import seed_demo_data

    with app.app_context():
        seed_demo_data()
        return Assessment.query.count()

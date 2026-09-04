"""`python -m pytest` from health/ puts the service dir on sys.path so tests can
`import app`, `import routes`, etc. as top-level modules."""

import pytest

from app import create_app
from config import Config


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


@pytest.fixture
def app(tmp_path):
    class _Config(Config):
        TESTING = True
        SEED_DEMO_DATA = False
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'health.db'}"

    application = create_app(_Config)
    application.extensions["ollama"] = FakeOllamaClient()
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

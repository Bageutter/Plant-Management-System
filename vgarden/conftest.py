"""Root-level so this directory lands on sys.path during test collection,
letting tests import app/routes/models/etc. as top-level modules, and so
fixtures here are shared by every test module.
"""

import os
import sys

import pytest

# The shared agentic-loop module (../shared/ai_loop.py), as app.py does at runtime.
_SHARED = os.path.join(os.path.dirname(__file__), "..", "shared")
if os.path.isdir(_SHARED) and _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)


class TestConfig:
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = "test-secret-key"
    INTER_SERVICE_SECRET = "test-inter-service-secret"
    AUTH_PUBLIC_URL = "http://auth.test"
    WTF_CSRF_ENABLED = False
    TESTING = True
    SEED_DEMO_DATA = False
    AI_LOOP_MAX_ITERATIONS = 2
    # OLLAMA_REVIEW_MODEL is deliberately unset -> build_reviewer() returns None;
    # the `ai_loop_reviewer` fixture below injects a fake instead.


@pytest.fixture
def app(tmp_path):
    """A fresh Flask app + SQLite file per test."""
    import app as app_module

    db_path = tmp_path / "test.db"

    class _Config(TestConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{db_path}"
        AI_LOOP_LOG_DIR = str(tmp_path / "ai-loop-logs")

    return app_module.create_app(_Config)


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def login_as(client):
    """login_as(user_id) puts a vgarden session cookie on `client` as if /sso had run."""

    def _login(user_id: int):
        with client.session_transaction() as sess:
            sess["user_id"] = user_id

    return _login


@pytest.fixture
def service_headers(app):
    return {"Authorization": f"Bearer {app.config['INTER_SERVICE_SECRET']}"}


class FakeWeather:
    """Stand-in for weather.OpenMeteoClient. Defaults to "Open-Meteo unreachable"
    so tests never touch the network; opt into results per-test."""

    def __init__(self):
        self.raise_error = True
        self.geocode_result = None
        self.weather_result = None
        self.geocode_calls = []
        self.weather_calls = []

    def geocode(self, name):
        self.geocode_calls.append(name)
        if self.raise_error:
            from weather import WeatherUnavailableError

            raise WeatherUnavailableError("test: offline")
        return self.geocode_result

    def garden_weather(self, latitude, longitude):
        self.weather_calls.append((latitude, longitude))
        if self.raise_error:
            from weather import WeatherUnavailableError

            raise WeatherUnavailableError("test: offline")
        return self.weather_result


@pytest.fixture(autouse=True)
def weather(app):
    """Autouse: every test gets an offline weather stub. Tests that exercise
    geocoding/forecast set `weather.raise_error = False` and the *_result fields."""
    fake = FakeWeather()
    app.extensions["weather"] = fake
    return fake


class FakeReviewer:
    """Stand-in for ai_loop.Reviewer. Emits verdicts from `script` (repeating the
    last one), so tests drive the Plan->Act->Observe->Adapt loop deterministically."""

    def __init__(self, script=None):
        self.script = list(script or ["approved"])
        self.calls = []

    def review(self, question, grounding, draft):
        self.calls.append({"question": question, "grounding": grounding, "draft": draft})
        verdict = self.script[min(len(self.calls) - 1, len(self.script) - 1)]
        if verdict == "approved":
            return {"verdict": "approved", "issues": [], "guidance": ""}
        return {
            "verdict": "revise",
            "issues": ["draft not grounded"],
            "guidance": f"fix iteration {len(self.calls)}",
        }


@pytest.fixture(autouse=True)
def ai_loop_reviewer(app):
    """Autouse: every test gets a reviewer that approves on the first pass
    (1 iteration, verdict 'approved'). Override `.script` for revision tests."""
    fake = FakeReviewer()
    app.extensions["ai_loop_reviewer"] = fake
    return fake

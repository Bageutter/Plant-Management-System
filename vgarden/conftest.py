"""Root-level so this directory lands on sys.path during test collection,
letting tests import app/routes/models/etc. as top-level modules, and so
fixtures here are shared by every test module.
"""

import pytest


class TestConfig:
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = "test-secret-key"
    INTER_SERVICE_SECRET = "test-inter-service-secret"
    AUTH_PUBLIC_URL = "http://auth.test"
    WTF_CSRF_ENABLED = False
    TESTING = True


@pytest.fixture
def app(tmp_path):
    """A fresh Flask app + SQLite file per test."""
    import app as app_module

    db_path = tmp_path / "test.db"

    class _Config(TestConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{db_path}"

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

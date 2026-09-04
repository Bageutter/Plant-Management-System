"""Root-level so this directory lands on sys.path during test collection,
letting tests import app/routes/models/etc. as top-level modules.
"""

import pytest


class TestConfig:
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = "test-secret-key"
    INTER_SERVICE_SECRET = "test-inter-service-secret"
    VGARDEN_URL = "http://vgarden.test"
    VGARDEN_PUBLIC_URL = "http://vgarden.test"
    WTF_CSRF_ENABLED = False
    TESTING = True
    SEED_DEMO_DATA = False


@pytest.fixture
def app(tmp_path):
    import app as app_module

    class _Config(TestConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'test.db'}"

    return app_module.create_app(_Config)


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def login_as(client):
    """login_as(user_id) authenticates `client` as that user via Flask-Login's session key."""

    def _login(user_id: int):
        with client.session_transaction() as sess:
            sess["_user_id"] = str(user_id)
            sess["_fresh"] = True

    return _login

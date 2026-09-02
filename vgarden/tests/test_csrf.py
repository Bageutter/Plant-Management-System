"""The rest of the suite disables CSRF (conftest.TestConfig) so form tests can
focus on business logic. This file re-enables it to check the protection
itself actually works, and that the service-to-service API stays exempt.
"""

from conftest import TestConfig
from extensions import db
from models import Garden


class CsrfEnabledConfig(TestConfig):
    WTF_CSRF_ENABLED = True


def _make_app(tmp_path):
    import app as app_module

    class _Config(CsrfEnabledConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'test.db'}"

    return app_module.create_app(_Config)


def test_browser_form_post_without_csrf_token_is_rejected(tmp_path):
    app = _make_app(tmp_path)
    client = app.test_client()

    with app.app_context():
        garden = Garden(owner_id=1, name="G")
        db.session.add(garden)
        db.session.commit()
        garden_id = garden.id

    with client.session_transaction() as sess:
        sess["user_id"] = 1

    response = client.post(f"/gardens/{garden_id}/areas", data={"name": "Bed", "area_type": "bed"})

    assert response.status_code == 400


def test_service_api_post_stays_exempt_from_csrf(tmp_path):
    app = _make_app(tmp_path)
    client = app.test_client()
    headers = {"Authorization": f"Bearer {app.config['INTER_SERVICE_SECRET']}"}

    response = client.post("/gardens", json={"owner_id": 1, "name": "G"}, headers=headers)

    assert response.status_code == 201

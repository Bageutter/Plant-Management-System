import auth_utils
from extensions import db
from models import Garden


def _make_token(app, user_id=1, email="owner@example.com"):
    with app.app_context():
        return auth_utils.make_sso_serializer().dumps({"user_id": user_id, "email": email})


def test_valid_token_sets_session_and_redirects(app, client):
    with app.app_context():
        garden = Garden(owner_id=1, name="G")
        db.session.add(garden)
        db.session.commit()
        garden_id = garden.id

    token = _make_token(app, user_id=1)
    response = client.get(f"/sso?token={token}&next=/gardens/{garden_id}/view", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["Location"] == f"/gardens/{garden_id}/view"

    with client.session_transaction() as sess:
        assert sess["user_id"] == 1


def test_invalid_token_redirects_to_auth_login(app, client):
    response = client.get("/sso?token=garbage&next=/gardens/1/view", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["Location"] == "http://auth.test/login"
    with client.session_transaction() as sess:
        assert "user_id" not in sess


def test_open_redirect_next_is_rejected(app, client):
    token = _make_token(app, user_id=1)
    response = client.get(f"/sso?token={token}&next=https://evil.example/", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["Location"] == "/"


def test_protocol_relative_next_is_rejected(app, client):
    token = _make_token(app, user_id=1)
    response = client.get(f"/sso?token={token}&next=//evil.example/", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["Location"] == "/"

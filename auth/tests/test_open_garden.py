from urllib.parse import parse_qs, urlparse

from itsdangerous import URLSafeTimedSerializer

from extensions import db
from models import Garden, User
from routes import SSO_SALT


def _make_user(app, email="owner@example.com") -> int:
    with app.app_context():
        user = User(email=email)
        user.set_password("password123")
        db.session.add(user)
        db.session.commit()
        return user.id


def _own_garden(app, user_id: int, garden_id: int = 42) -> None:
    with app.app_context():
        db.session.add(Garden(garden_id=garden_id, user_id=user_id))
        db.session.commit()


def test_open_garden_requires_login(client):
    response = client.get("/gardens/42/open", follow_redirects=False)
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_open_garden_404s_when_not_owned(app, client, login_as):
    user_id = _make_user(app)
    login_as(user_id)

    response = client.get("/gardens/42/open")

    assert response.status_code == 404


def test_open_garden_redirects_with_valid_token(app, client, login_as):
    user_id = _make_user(app)
    _own_garden(app, user_id, garden_id=42)
    login_as(user_id)

    response = client.get("/gardens/42/open", follow_redirects=False)

    assert response.status_code == 302
    location = response.headers["Location"]
    assert location.startswith("http://vgarden.test/sso?")

    query = parse_qs(urlparse(location).query)
    assert query["next"] == ["/gardens/42/view"]

    with app.app_context():
        serializer = URLSafeTimedSerializer(app.config["INTER_SERVICE_SECRET"], salt=SSO_SALT)
        data = serializer.loads(query["token"][0], max_age=60)
    assert data["user_id"] == user_id
    assert data["email"] == "owner@example.com"


def test_open_garden_404s_for_someone_elses_garden(app, client, login_as):
    owner_id = _make_user(app, email="owner@example.com")
    stranger_id = _make_user(app, email="stranger@example.com")
    _own_garden(app, owner_id, garden_id=42)
    login_as(stranger_id)

    response = client.get("/gardens/42/open")

    assert response.status_code == 404

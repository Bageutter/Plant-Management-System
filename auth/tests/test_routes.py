"""Auth's own routes: register, log out, the account page, adding and deleting a
garden, and /me.

Auth talks to vgarden over HTTP with `requests`. FakeVgarden replaces those calls,
so nothing here touches the network. It records each call, so the tests can check
the service token and the owner scoping auth sends.
"""

import pytest
import requests

import routes
from extensions import db
from models import Garden, User

PASSWORD = "correct-horse-battery"  # noqa: S105 -- fake, test-only value  # pragma: allowlist secret


class FakeResponse:
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self._body = body

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class FakeVgarden:
    """Stands in for the vgarden service API that auth calls."""

    def __init__(self):
        self.gardens = {}  # garden_id -> {"id", "name", "owner_id"}
        self.calls = []
        self.down = False
        self.next_id = 100

    def _record(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if self.down:
            raise requests.ConnectionError("vgarden is down")

    def get(self, url, params=None, headers=None, timeout=None):
        self._record("GET", url, params=params, headers=headers)
        if url.endswith("/gardens"):
            owner = int(params["owner_id"])
            return FakeResponse(200, [g for g in self.gardens.values() if g["owner_id"] == owner])
        garden = self.gardens.get(int(url.rsplit("/", 1)[1]))
        return FakeResponse(200, garden) if garden else FakeResponse(404, {"error": "not found"})

    def post(self, url, json=None, headers=None, timeout=None):
        self._record("POST", url, json=json, headers=headers)
        garden = {"id": self.next_id, "name": json["name"], "owner_id": json["owner_id"]}
        self.gardens[self.next_id] = garden
        self.next_id += 1
        return FakeResponse(201, garden)

    def delete(self, url, headers=None, timeout=None):
        self._record("DELETE", url, headers=headers)
        return FakeResponse(204) if self.gardens.pop(int(url.rsplit("/", 1)[1]), None) else FakeResponse(404)


@pytest.fixture(autouse=True)
def public_urls(app):
    # The real Config always sets these; the shared TestConfig leaves them out.
    app.config.setdefault("HEALTH_PUBLIC_URL", "http://health.test/plant-health-records/")
    app.config.setdefault("ALMANAC_PUBLIC_URL", "http://almanac.test/")


@pytest.fixture
def vgarden(monkeypatch):
    fake = FakeVgarden()
    for method in ("get", "post", "delete"):
        monkeypatch.setattr(routes.requests, method, getattr(fake, method))
    return fake


def make_user(app, email="owner@example.com"):
    with app.app_context():
        user = User(email=email)
        user.set_password(PASSWORD)
        db.session.add(user)
        db.session.commit()
        return user.id


def own(app, user_id, garden_id):
    with app.app_context():
        db.session.add(Garden(garden_id=garden_id, user_id=user_id))
        db.session.commit()


def ownerships(app, user_id):
    with app.app_context():
        return sorted(g.garden_id for g in Garden.query.filter_by(user_id=user_id))


# --- register ---


def test_register_creates_the_account_and_logs_in(app, client):
    response = client.post("/register", data={
        "email": "New@Example.com", "password": PASSWORD, "confirm_password": PASSWORD})

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/account")
    with app.app_context():
        user = User.query.filter_by(email="new@example.com").one()  # lower-cased
        assert user.check_password(PASSWORD)
        assert user.password_hash != PASSWORD
    assert client.get("/me").get_json()["email"] == "new@example.com"


def test_register_rejects_a_duplicate_email(app, client):
    make_user(app, "taken@example.com")

    response = client.post("/register", data={
        "email": "TAKEN@example.com", "password": PASSWORD, "confirm_password": PASSWORD})

    assert response.status_code == 200
    assert b"An account with this email already exists." in response.data
    with app.app_context():
        assert User.query.count() == 1


@pytest.mark.parametrize("data, message", [
    ({"email": "not-an-email", "password": PASSWORD, "confirm_password": PASSWORD}, b"Invalid email"),
    ({"email": "a@example.com", "password": "short", "confirm_password": "short"}, b"Use at least 8 characters."),  # pragma: allowlist secret -- fake test values
    ({"email": "a@example.com", "password": PASSWORD, "confirm_password": "different1"}, b"Passwords must match."),  # pragma: allowlist secret -- fake test values
])
def test_register_validates_the_form(app, client, data, message):
    response = client.post("/register", data=data)

    assert response.status_code == 200
    assert message in response.data
    with app.app_context():
        assert User.query.count() == 0


def test_register_sends_a_logged_in_user_to_their_account(app, client, login_as):
    login_as(make_user(app))

    response = client.get("/register")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/account")


# --- log out ---


def test_logout_ends_the_session(app, client, login_as):
    login_as(make_user(app))

    response = client.post("/logout")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login")
    assert client.get("/me").status_code == 302  # back to the login page


def test_logout_needs_post(app, client, login_as):
    login_as(make_user(app))

    assert client.get("/logout").status_code == 405
    assert client.get("/me").status_code == 200


# --- account page ---


def test_account_lists_only_this_users_gardens(app, client, login_as, vgarden):
    owner = make_user(app)
    other = make_user(app, "other@example.com")
    vgarden.gardens = {
        1: {"id": 1, "name": "Backyard", "owner_id": owner},
        2: {"id": 2, "name": "Someone else's plot", "owner_id": other},
    }
    own(app, owner, 1)
    own(app, other, 2)
    login_as(owner)

    response = client.get("/account")

    assert response.status_code == 200
    assert b"Backyard" in response.data
    assert b"Someone else" not in response.data
    method, url, kwargs = vgarden.calls[0]
    assert (method, url, kwargs["params"]) == ("GET", "http://vgarden.test/gardens", {"owner_id": owner})
    assert kwargs["headers"] == {"Authorization": "Bearer test-inter-service-secret"}


def test_account_without_gardens_does_not_call_vgarden(app, client, login_as, vgarden):
    login_as(make_user(app))

    assert client.get("/account").status_code == 200
    assert vgarden.calls == []


def test_account_still_renders_when_vgarden_is_down(app, client, login_as, vgarden):
    owner = make_user(app)
    own(app, owner, 1)
    vgarden.down = True
    login_as(owner)

    response = client.get("/account")

    assert response.status_code == 200
    assert b"t load your gardens right now." in response.data


@pytest.mark.parametrize("path", ["/account", "/me"])
def test_pages_need_login(client, path):
    response = client.get(path)

    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


# --- add a garden ---


def test_create_garden_records_ownership(app, client, login_as, vgarden):
    owner = make_user(app)
    login_as(owner)

    response = client.post("/gardens", data={"name": "  Balcony ", "location": "Melbourne"})

    assert response.status_code == 302
    method, url, kwargs = vgarden.calls[0]
    assert (method, url) == ("POST", "http://vgarden.test/gardens")
    assert kwargs["json"] == {"owner_id": owner, "name": "Balcony", "location": "Melbourne"}
    assert ownerships(app, owner) == [100]


def test_create_garden_needs_a_name(app, client, login_as, vgarden):
    owner = make_user(app)
    login_as(owner)

    response = client.post("/gardens", data={"name": "   "}, follow_redirects=True)

    assert b"Garden name is required." in response.data
    assert vgarden.calls == []
    assert ownerships(app, owner) == []


def test_create_garden_records_nothing_when_vgarden_fails(app, client, login_as, vgarden, monkeypatch):
    owner = make_user(app)
    login_as(owner)
    monkeypatch.setattr(routes.requests, "post", lambda *a, **k: FakeResponse(500, {}))

    response = client.post("/gardens", data={"name": "Balcony"}, follow_redirects=True)

    assert b"t create that garden." in response.data
    assert ownerships(app, owner) == []


def test_create_garden_when_vgarden_is_down(app, client, login_as, vgarden):
    owner = make_user(app)
    vgarden.down = True
    login_as(owner)

    response = client.post("/gardens", data={"name": "Balcony"}, follow_redirects=True)

    assert b"t reach the garden service." in response.data
    assert ownerships(app, owner) == []


# --- delete a garden ---


def test_delete_garden_needs_the_exact_name(app, client, login_as, vgarden):
    owner = make_user(app)
    vgarden.gardens = {7: {"id": 7, "name": "Backyard", "owner_id": owner}}
    own(app, owner, 7)
    login_as(owner)

    response = client.post("/gardens/7/delete", data={"confirm_name": "backyard"}, follow_redirects=True)

    assert b"Nothing was deleted." in response.data
    assert 7 in vgarden.gardens
    assert ownerships(app, owner) == [7]


def test_delete_garden_removes_it_in_vgarden_and_auth(app, client, login_as, vgarden):
    owner = make_user(app)
    vgarden.gardens = {7: {"id": 7, "name": "Backyard", "owner_id": owner}}
    own(app, owner, 7)
    login_as(owner)

    response = client.post("/gardens/7/delete", data={"confirm_name": "Backyard"}, follow_redirects=True)

    assert b"Deleted &#34;Backyard&#34;." in response.data or b'Deleted "Backyard".' in response.data
    assert vgarden.gardens == {}
    assert ownerships(app, owner) == []


def test_cannot_delete_someone_elses_garden(app, client, login_as, vgarden):
    owner = make_user(app)
    intruder = make_user(app, "intruder@example.com")
    vgarden.gardens = {7: {"id": 7, "name": "Backyard", "owner_id": owner}}
    own(app, owner, 7)
    login_as(intruder)

    response = client.post("/gardens/7/delete", data={"confirm_name": "Backyard"}, follow_redirects=True)

    assert b"Garden not found." in response.data
    assert vgarden.calls == []  # never asks vgarden about a garden it doesn't own
    assert 7 in vgarden.gardens
    assert ownerships(app, owner) == [7]


def test_delete_garden_keeps_ownership_when_vgarden_is_down(app, client, login_as, vgarden):
    owner = make_user(app)
    own(app, owner, 7)
    vgarden.down = True
    login_as(owner)

    response = client.post("/gardens/7/delete", data={"confirm_name": "Backyard"}, follow_redirects=True)

    assert b"t reach the garden service." in response.data
    assert ownerships(app, owner) == [7]


# --- /me ---


def test_me_returns_only_id_and_email(app, client, login_as):
    user_id = make_user(app)
    login_as(user_id)

    assert client.get("/me").get_json() == {"id": user_id, "email": "owner@example.com"}

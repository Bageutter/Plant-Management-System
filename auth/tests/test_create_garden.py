"""create_garden records ownership from the garden service's response, and
self-heals when the garden id has been recycled (SQLite reuses row ids, and a
stale/out-of-step database can leave an ownership row for a reused id)."""

import routes
from extensions import db
from models import Garden, User


class _Resp:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


def _user(app, email):
    with app.app_context():
        u = User(email=email)
        u.set_password("password123")
        db.session.add(u)
        db.session.commit()
        return u.id


def test_create_garden_records_ownership(app, client, login_as, monkeypatch):
    uid = _user(app, "a@example.com")
    login_as(uid)
    monkeypatch.setattr(routes.requests, "post", lambda *a, **k: _Resp(201, {"id": 7}))

    resp = client.post("/gardens", data={"name": "My Plot"}, follow_redirects=False)

    assert resp.status_code == 302
    with app.app_context():
        row = Garden.query.filter_by(garden_id=7).one()
        assert row.user_id == uid


def test_create_garden_replaces_a_stale_ownership_row_for_a_reused_id(app, client, login_as, monkeypatch):
    owner = _user(app, "owner@example.com")
    newcomer = _user(app, "newcomer@example.com")
    with app.app_context():
        db.session.add(Garden(garden_id=5, user_id=owner))  # stale row from an old garden
        db.session.commit()

    login_as(newcomer)
    monkeypatch.setattr(routes.requests, "post", lambda *a, **k: _Resp(201, {"id": 5}))

    resp = client.post("/gardens", data={"name": "Fresh Garden"}, follow_redirects=False)

    assert resp.status_code == 302
    with app.app_context():
        rows = Garden.query.filter_by(garden_id=5).all()
        assert len(rows) == 1
        assert rows[0].user_id == newcomer


def test_create_garden_needs_a_name(app, client, login_as):
    login_as(_user(app, "b@example.com"))
    resp = client.post("/gardens", data={"name": "  "}, follow_redirects=False)
    assert resp.status_code == 302
    with app.app_context():
        assert Garden.query.count() == 0

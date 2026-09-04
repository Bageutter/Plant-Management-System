"""Login accepts a reserved-domain address (the seeded demo account is
demo@plant.test, and email_validator rejects the .test TLD — the login form
must not run that check)."""

from extensions import db
from models import User


def _make_user(app, email, password="demogarden"):
    with app.app_context():
        u = User(email=email)
        u.set_password(password)
        db.session.add(u)
        db.session.commit()


def test_login_accepts_a_reserved_domain_address(app, client):
    _make_user(app, "demo@plant.test")

    resp = client.post(
        "/login",
        data={"email": "demo@plant.test", "password": "demogarden"},
        follow_redirects=False,
    )

    assert resp.status_code == 302
    assert "/account" in resp.headers["Location"]


def test_login_rejects_a_wrong_password_without_leaking_which_field(app, client):
    _make_user(app, "demo@plant.test")

    resp = client.post(
        "/login",
        data={"email": "demo@plant.test", "password": "wrong"},
        follow_redirects=True,
    )

    assert resp.status_code == 200
    assert b"Invalid email or password." in resp.data

"""Behind the nginx proxy, auth is mounted at /auth. ProxyFix reads
X-Forwarded-Prefix so url_for()/redirects come back with the /auth prefix.
"""

from extensions import db
from models import User

PROXY = {"X-Forwarded-Prefix": "/auth", "X-Forwarded-Proto": "https"}


def _make_user(app, email="o@example.com", password="password123"):
    with app.app_context():
        user = User(email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()


def test_login_redirect_keeps_the_proxy_prefix(app, client):
    _make_user(app)

    response = client.post(
        "/login",
        data={"email": "o@example.com", "password": "password123"},
        headers=PROXY,
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["Location"] == "/auth/account"


def test_login_page_links_are_under_the_prefix(app, client):
    response = client.get("/login", headers=PROXY)

    assert response.status_code == 200
    assert b'href="/auth/register"' in response.data


def test_no_prefix_header_leaves_paths_untouched(app, client):
    _make_user(app)

    response = client.post(
        "/login",
        data={"email": "o@example.com", "password": "password123"},
        follow_redirects=False,
    )

    assert response.headers["Location"] == "/account"

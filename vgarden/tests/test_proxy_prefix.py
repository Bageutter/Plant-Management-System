"""Behind the nginx proxy, vgarden is mounted at /vgarden. ProxyFix reads
X-Forwarded-Prefix so url_for() and the SSO landing redirect carry that prefix.
"""

import auth_utils
from extensions import db
from models import Garden

PROXY = {"X-Forwarded-Prefix": "/vgarden", "X-Forwarded-Proto": "https"}


def _make_garden(app, owner_id=1):
    with app.app_context():
        garden = Garden(owner_id=owner_id, name="G")
        db.session.add(garden)
        db.session.commit()
        return garden.id


def test_sso_landing_redirect_keeps_the_proxy_prefix(app, client):
    garden_id = _make_garden(app)
    with app.app_context():
        token = auth_utils.make_sso_serializer().dumps({"user_id": 1, "email": "o@x.com"})

    response = client.get(
        f"/sso?token={token}&next=/gardens/{garden_id}/view",
        headers=PROXY,
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["Location"] == f"/vgarden/gardens/{garden_id}/view"


def test_edit_redirect_keeps_the_proxy_prefix(app, client, login_as):
    garden_id = _make_garden(app, owner_id=1)
    login_as(1)

    response = client.post(
        f"/gardens/{garden_id}/edit",
        data={"name": "Renamed"},
        headers=PROXY,
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["Location"] == f"/vgarden/gardens/{garden_id}/view"


def test_no_prefix_header_leaves_paths_untouched(app, client):
    garden_id = _make_garden(app)
    with app.app_context():
        token = auth_utils.make_sso_serializer().dumps({"user_id": 1})

    response = client.get(
        f"/sso?token={token}&next=/gardens/{garden_id}/view", follow_redirects=False
    )

    assert response.headers["Location"] == f"/gardens/{garden_id}/view"

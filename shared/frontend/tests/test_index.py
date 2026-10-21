"""The landing page served at the proxy root."""

from conftest import URLS


def test_index_links_to_every_service(client):
    response = client.get("/")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert f'href="{URLS["AUTH_URL"]}/register"' in html  # Get started
    assert f'href="{URLS["AUTH_URL"]}/login"' in html
    assert f'{URLS["AUTH_URL"]}/account' in html  # My Gardens
    assert URLS["HEALTH_URL"] in html
    assert f'href="{URLS["ALMANAC_URL"]}"' in html


def test_index_uses_the_configured_urls_not_the_local_defaults(client):
    html = client.get("/").get_data(as_text=True)

    assert "localhost:5001" not in html
    assert "localhost:5003" not in html
    assert "localhost:5004" not in html


def test_unknown_paths_are_404(client):
    assert client.get("/no-such-page").status_code == 404

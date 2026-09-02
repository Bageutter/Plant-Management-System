from extensions import db
from models import Garden


def _make_garden(app, owner_id=1, name="G"):
    with app.app_context():
        garden = Garden(owner_id=owner_id, name=name)
        db.session.add(garden)
        db.session.commit()
        return garden.id


# --- service-to-service API ---


def test_create_garden_requires_service_token(client):
    response = client.post("/gardens", json={"owner_id": 1, "name": "G"})
    assert response.status_code == 401


def test_create_garden_rejects_wrong_token(client):
    response = client.post(
        "/gardens", json={"owner_id": 1, "name": "G"}, headers={"Authorization": "Bearer wrong"}
    )
    assert response.status_code == 401


def test_create_garden_succeeds_with_correct_token(client, service_headers):
    response = client.post("/gardens", json={"owner_id": 1, "name": "G"}, headers=service_headers)
    assert response.status_code == 201
    assert response.get_json()["name"] == "G"


def test_create_garden_geocodes_the_location(client, service_headers, weather):
    weather.raise_error = False
    weather.geocode_result = {
        "label": "Melbourne, Victoria, Australia",
        "latitude": -37.81,
        "longitude": 144.96,
    }

    response = client.post(
        "/gardens",
        json={"owner_id": 1, "name": "G", "location": "Melbourne"},
        headers=service_headers,
    )

    assert response.status_code == 201
    body = response.get_json()
    assert body["location_label"] == "Melbourne, Victoria, Australia"
    assert body["latitude"] == -37.81
    assert weather.geocode_calls == ["Melbourne"]


def test_create_garden_keeps_raw_label_when_geocoding_misses(client, service_headers, weather):
    weather.raise_error = False
    weather.geocode_result = None  # nothing matched

    response = client.post(
        "/gardens",
        json={"owner_id": 1, "name": "G", "location": "Nowheresville"},
        headers=service_headers,
    )

    assert response.status_code == 201
    body = response.get_json()
    assert body["location_label"] == "Nowheresville"
    assert body["latitude"] is None


def test_create_garden_survives_weather_outage(client, service_headers, weather):
    weather.raise_error = True  # Open-Meteo unreachable

    response = client.post(
        "/gardens",
        json={"owner_id": 1, "name": "G", "location": "Melbourne"},
        headers=service_headers,
    )

    assert response.status_code == 201
    assert response.get_json()["location_label"] == "Melbourne"


def test_list_gardens_requires_service_token(client):
    assert client.get("/gardens", query_string={"owner_id": 1}).status_code == 401


def test_get_garden_requires_service_token(app, client):
    garden_id = _make_garden(app)
    assert client.get(f"/gardens/{garden_id}").status_code == 401


def test_delete_garden_requires_service_token(app, client):
    garden_id = _make_garden(app)
    assert client.delete(f"/gardens/{garden_id}").status_code == 401


def test_delete_garden_succeeds_with_correct_token(app, client, service_headers):
    garden_id = _make_garden(app)
    response = client.delete(f"/gardens/{garden_id}", headers=service_headers)
    assert response.status_code == 204
    with app.app_context():
        assert db.session.get(Garden, garden_id) is None


# --- browser-facing view page ---


def test_view_garden_requires_login(app, client):
    garden_id = _make_garden(app)
    response = client.get(f"/gardens/{garden_id}/view", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["Location"] == "http://auth.test/login"


def test_view_garden_404s_for_nonexistent_garden(client, login_as):
    login_as(1)
    assert client.get("/gardens/999999/view").status_code == 404


def test_view_garden_404s_for_non_owner(app, client, login_as):
    garden_id = _make_garden(app, owner_id=1)
    login_as(2)
    assert client.get(f"/gardens/{garden_id}/view").status_code == 404


def test_view_garden_succeeds_for_owner(app, client, login_as):
    garden_id = _make_garden(app, owner_id=1, name="My Garden")
    login_as(1)
    response = client.get(f"/gardens/{garden_id}/view")
    assert response.status_code == 200
    assert b"My Garden" in response.data


def test_edit_garden_updates_fields_and_geocodes_the_location(app, client, login_as, weather):
    garden_id = _make_garden(app, owner_id=1, name="Old name")
    login_as(1)
    weather.raise_error = False
    weather.geocode_result = {
        "label": "Melbourne, Victoria, Australia",
        "latitude": -37.81,
        "longitude": 144.96,
        "timezone": "Australia/Melbourne",
    }

    response = client.post(
        f"/gardens/{garden_id}/edit",
        data={
            "name": "New name",
            "description": "A lovely garden",
            "location_label": "Melbourne",
            "climate_zone": "temperate",
            "map_width_m": "20",
            "map_height_m": "15",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert weather.geocode_calls == ["Melbourne"]
    with app.app_context():
        garden = db.session.get(Garden, garden_id)
        assert garden.name == "New name"
        assert garden.description == "A lovely garden"
        assert garden.location_label == "Melbourne, Victoria, Australia"
        assert garden.latitude == -37.81
        assert garden.map_width_m == 20.0


def test_edit_garden_clearing_the_location_drops_coordinates(app, client, login_as, weather):
    garden_id = _make_garden(app, owner_id=1)
    login_as(1)
    weather.raise_error = False
    weather.geocode_result = {"label": "Berlin", "latitude": 52.5, "longitude": 13.4}
    client.post(f"/gardens/{garden_id}/edit", data={"name": "G", "location_label": "Berlin"})

    client.post(f"/gardens/{garden_id}/edit", data={"name": "G", "location_label": ""})

    with app.app_context():
        garden = db.session.get(Garden, garden_id)
        assert garden.location_label == ""
        assert garden.latitude is None


def test_edit_garden_404s_for_non_owner(app, client, login_as):
    garden_id = _make_garden(app, owner_id=1)
    login_as(2)
    response = client.post(f"/gardens/{garden_id}/edit", data={"name": "Hacked"})
    assert response.status_code == 404

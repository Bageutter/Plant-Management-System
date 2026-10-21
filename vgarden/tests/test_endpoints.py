"""Release 2 post-commit endpoint tests for the two assigned Virtual Garden backend
functions, run by name in .github/workflows/vgarden.yml:

- ``routes.create_garden``   POST /gardens
- ``routes.garden_snapshot`` GET  /gardens/<id>/snapshot

Each test covers one function end to end: service-token auth, input validation,
the success response and what is (or is not) written to the database. Temporary
SQLite per test, weather stubbed offline, no live MCP/RAG/Ollama needed.
"""

from datetime import date

from extensions import db
from models import Container, Garden, GardenArea, Planting, PlantingLocation


def _garden_count(app):
    with app.app_context():
        return Garden.query.count()


def test_healthz_returns_service_status(client):
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok", "service": "vgarden"}


def test_list_gardens_filters_results_by_owner(app, client, service_headers):
    assert client.get("/gardens").status_code == 401
    assert client.get("/gardens", headers={"Authorization": "******"}).status_code == 401

    with app.app_context():
        db.session.add_all(
            [
                Garden(owner_id=7, name="Backyard"),
                Garden(owner_id=8, name="Community plot"),
            ]
        )
        db.session.commit()

    all_gardens = client.get("/gardens", headers=service_headers)
    assert all_gardens.status_code == 200
    assert {garden["name"] for garden in all_gardens.get_json()} == {
        "Backyard",
        "Community plot",
    }

    response = client.get("/gardens", query_string={"owner_id": 7}, headers=service_headers)

    assert response.status_code == 200
    gardens = response.get_json()
    assert len(gardens) == 1
    assert gardens[0]["owner_id"] == 7
    assert gardens[0]["name"] == "Backyard"
    empty = client.get("/gardens", query_string={"owner_id": 99}, headers=service_headers)
    assert empty.status_code == 200
    assert empty.get_json() == []


def test_create_garden_validates_input_and_persists(app, client, service_headers, weather):
    payload = {"owner_id": 7, "name": "  Backyard  ", "location": "Melbourne"}

    # Auth: no token and a wrong token are both refused before anything is written.
    assert client.post("/gardens", json=payload).status_code == 401
    wrong = {"Authorization": "Bearer wrong"}
    assert client.post("/gardens", json=payload, headers=wrong).status_code == 401

    # Validation: each bad body is a 400 with a reason, and nothing is written.
    bad_bodies = [
        {"name": "G"},  # owner_id missing
        {"owner_id": "7", "name": "G"},  # owner_id not an integer
        {"owner_id": 7},  # name missing
        {"owner_id": 7, "name": "   "},  # name blank
        {"owner_id": 7, "name": "x" * 121},  # name too long
    ]
    for body in bad_bodies:
        response = client.post("/gardens", json=body, headers=service_headers)
        assert response.status_code == 400, body
        assert "error" in response.get_json()
    assert client.post("/gardens", data="not json", headers=service_headers).status_code == 400
    assert _garden_count(app) == 0

    # Success: trimmed name, geocoded location, 201 with the stored record.
    weather.raise_error = False
    weather.geocode_result = {
        "label": "Melbourne, Victoria, Australia",
        "latitude": -37.81,
        "longitude": 144.96,
    }
    response = client.post("/gardens", json=payload, headers=service_headers)
    assert response.status_code == 201
    body = response.get_json()
    assert body["owner_id"] == 7
    assert body["name"] == "Backyard"
    assert body["location_label"] == "Melbourne, Victoria, Australia"
    assert (body["latitude"], body["longitude"]) == (-37.81, 144.96)
    assert weather.geocode_calls == ["Melbourne"]

    # Persistence: exactly one row, readable back through the API.
    assert _garden_count(app) == 1
    fetched = client.get(f"/gardens/{body['id']}", headers=service_headers)
    assert fetched.status_code == 200
    assert fetched.get_json() == body


def _full_garden(app, owner_id=1):
    with app.app_context():
        garden = Garden(owner_id=owner_id, name="Backyard", location_label="Melbourne", climate_zone="temperate")
        db.session.add(garden)
        db.session.flush()

        area = GardenArea(garden_id=garden.id, name="North bed", area_type="bed", width=2, length=3)
        db.session.add(area)
        db.session.flush()
        db.session.add(Container(garden_area_id=area.id, name="Patio pot", container_type="pot"))

        planting = Planting(
            garden_id=garden.id,
            crop_name="Tomato",
            quantity=3,
            lifecycle_state="growing",
            growth_stage="flowering",
            planted_date=date(2026, 9, 1),
        )
        db.session.add(planting)
        db.session.flush()
        db.session.add(PlantingLocation(planting_id=planting.id, garden_area_id=area.id))
        db.session.commit()
        return garden.id


def test_garden_snapshot_returns_scoped_evidence_and_makes_no_writes(app, client, service_headers):
    garden_id = _full_garden(app)
    other_id = _full_garden(app, owner_id=2)
    url = f"/gardens/{garden_id}/snapshot"

    # Auth: private garden data needs the service token.
    assert client.get(url).status_code == 401
    assert client.get(url, headers={"Authorization": "Bearer wrong"}).status_code == 401

    # Unknown garden is a 404, not an empty snapshot.
    missing = client.get("/gardens/999999/snapshot", headers=service_headers)
    assert missing.status_code == 404
    assert missing.get_json() == {"error": "garden not found"}

    # Success: the garden's own areas, containers and plantings.
    response = client.get(url, headers=service_headers)
    assert response.status_code == 200
    body = response.get_json()
    assert body["garden_id"] == garden_id
    assert body["name"] == "Backyard"
    assert body["location_label"] == "Melbourne"
    assert body["climate_zone"] == "temperate"
    assert [a["name"] for a in body["areas"]] == ["North bed"]
    assert [c["name"] for c in body["containers"]] == ["Patio pot"]
    assert len(body["plantings"]) == 1
    planting = body["plantings"][0]
    assert planting["crop_name"] == "Tomato"
    assert planting["quantity"] == 3
    assert planting["lifecycle_state"] == "growing"
    assert planting["planted_date"] == "2026-09-01"
    assert planting["location"] == "area: North bed"
    assert "owner" in body["evidence_note"].lower()

    # Isolation: the other owner's garden is a separate snapshot with its own ids.
    other = client.get(f"/gardens/{other_id}/snapshot", headers=service_headers).get_json()
    assert other["garden_id"] == other_id
    assert {a["id"] for a in other["areas"]}.isdisjoint({a["id"] for a in body["areas"]})

    # Read-only: repeated reads return the same data and change nothing.
    with app.app_context():
        before = (Garden.query.count(), GardenArea.query.count(), Planting.query.count())
    assert client.get(url, headers=service_headers).get_json() == body
    with app.app_context():
        assert (Garden.query.count(), GardenArea.query.count(), Planting.query.count()) == before

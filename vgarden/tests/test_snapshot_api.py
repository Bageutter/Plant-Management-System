"""Service-token-authenticated endpoints the shared MCP/RAG servers read garden
state through (never the database). Garden data is private per-owner, so these
behave like the existing /gardens API above them: 401 without the shared secret.
"""

from datetime import date

from extensions import db
from models import Container, Garden, GardenArea, Planting, PlantingLocation


def _full_garden(app, owner_id=1):
    with app.app_context():
        garden = Garden(owner_id=owner_id, name="Backyard", location_label="Melbourne", climate_zone="temperate")
        db.session.add(garden)
        db.session.flush()

        area = GardenArea(garden_id=garden.id, name="North bed", area_type="bed", width=2, length=3)
        db.session.add(area)
        db.session.flush()

        container = Container(garden_area_id=area.id, name="Patio pot", container_type="pot")
        db.session.add(container)
        db.session.flush()

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


def test_garden_snapshot_requires_service_token(app, client):
    garden_id = _full_garden(app)
    assert client.get(f"/gardens/{garden_id}/snapshot").status_code == 401


def test_garden_snapshot_404s_for_missing_garden(client, service_headers):
    assert client.get("/gardens/999999/snapshot", headers=service_headers).status_code == 404


def test_garden_snapshot_shape(app, client, service_headers):
    garden_id = _full_garden(app)
    body = client.get(f"/gardens/{garden_id}/snapshot", headers=service_headers).get_json()

    assert body["garden_id"] == garden_id
    assert body["name"] == "Backyard"
    assert body["location_label"] == "Melbourne"
    assert body["climate_zone"] == "temperate"
    assert len(body["areas"]) == 1 and body["areas"][0]["name"] == "North bed"
    assert len(body["containers"]) == 1 and body["containers"][0]["name"] == "Patio pot"
    assert len(body["plantings"]) == 1
    planting = body["plantings"][0]
    assert planting["crop_name"] == "Tomato"
    assert planting["quantity"] == 3
    assert planting["lifecycle_state"] == "growing"
    assert planting["planted_date"] == "2026-09-01"
    assert planting["location"] == "area: North bed"
    assert "owner" in body["evidence_note"].lower()


def test_garden_plantings_requires_service_token(app, client):
    garden_id = _full_garden(app)
    assert client.get(f"/gardens/{garden_id}/plantings").status_code == 401


def test_garden_plantings_404s_for_missing_garden(client, service_headers):
    assert client.get("/gardens/999999/plantings", headers=service_headers).status_code == 404


def test_garden_plantings_shape(app, client, service_headers):
    garden_id = _full_garden(app)
    body = client.get(f"/gardens/{garden_id}/plantings", headers=service_headers).get_json()
    assert body == {
        "garden_id": garden_id,
        "count": 1,
        "items": body["items"],  # shape asserted below
    }
    assert body["items"][0]["crop_name"] == "Tomato"


def test_export_gardens_requires_service_token(client):
    assert client.get("/gardens/export").status_code == 401


def test_export_gardens_returns_every_garden_across_owners(app, client, service_headers):
    first = _full_garden(app, owner_id=1)
    with app.app_context():
        other = Garden(owner_id=2, name="Rooftop")
        db.session.add(other)
        db.session.commit()
        second = other.id

    body = client.get("/gardens/export", headers=service_headers).get_json()
    ids = {g["garden_id"] for g in body}
    assert ids == {first, second}
    rooftop = next(g for g in body if g["garden_id"] == second)
    assert rooftop["areas"] == [] and rooftop["plantings"] == []

from extensions import db
from models import Container, Garden, GardenArea, Planting, PlantingLocation


def _make_garden_with_area(app, owner_id=1):
    with app.app_context():
        garden = Garden(owner_id=owner_id, name="G")
        db.session.add(garden)
        db.session.commit()
        area = GardenArea(garden_id=garden.id, name="North bed", area_type="bed")
        db.session.add(area)
        db.session.commit()
        return garden.id, area.id


def test_create_container(app, client, login_as):
    garden_id, area_id = _make_garden_with_area(app)
    login_as(1)

    response = client.post(
        f"/gardens/{garden_id}/containers",
        data={"name": "Pot A", "container_type": "pot", "garden_area_id": str(area_id), "pos_x": "0", "pos_y": "0"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Pot A" in response.data
    with app.app_context():
        container = Container.query.filter_by(garden_area_id=area_id).one()
        assert container.name == "Pot A"


def test_create_container_requires_valid_area_in_same_garden(app, client, login_as):
    garden_id, _ = _make_garden_with_area(app)
    login_as(1)

    response = client.post(
        f"/gardens/{garden_id}/containers",
        data={"name": "Pot A", "container_type": "pot", "garden_area_id": "999999"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    with app.app_context():
        assert Container.query.count() == 0


def test_create_container_404s_for_non_owner(app, client, login_as):
    garden_id, area_id = _make_garden_with_area(app, owner_id=1)
    login_as(2)

    response = client.post(
        f"/gardens/{garden_id}/containers",
        data={"name": "Sneaky pot", "container_type": "pot", "garden_area_id": str(area_id)},
    )

    assert response.status_code == 404


def _make_container(app, area_id):
    with app.app_context():
        container = Container(garden_area_id=area_id, name="Pot A")
        db.session.add(container)
        db.session.commit()
        return container.id


def test_view_container_404s_for_non_owner(app, client, login_as):
    garden_id, area_id = _make_garden_with_area(app, owner_id=1)
    container_id = _make_container(app, area_id)
    login_as(2)

    assert client.get(f"/gardens/{garden_id}/containers/{container_id}").status_code == 404


def test_edit_container_reassigns_area(app, client, login_as):
    garden_id, area_id = _make_garden_with_area(app)
    with app.app_context():
        other_area = GardenArea(garden_id=garden_id, name="South bed", area_type="bed")
        db.session.add(other_area)
        db.session.commit()
        other_area_id = other_area.id
    container_id = _make_container(app, area_id)
    login_as(1)

    response = client.post(
        f"/gardens/{garden_id}/containers/{container_id}/edit",
        data={"name": "Pot A", "container_type": "pot", "garden_area_id": str(other_area_id)},
        follow_redirects=True,
    )

    assert response.status_code == 200
    with app.app_context():
        assert db.session.get(Container, container_id).garden_area_id == other_area_id


def test_delete_container_cascades_plantings(app, client, login_as):
    garden_id, area_id = _make_garden_with_area(app)
    container_id = _make_container(app, area_id)
    with app.app_context():
        planting = Planting(garden_id=garden_id, crop_name="Basil")
        db.session.add(planting)
        db.session.commit()
        db.session.add(PlantingLocation(planting_id=planting.id, container_id=container_id))
        db.session.commit()

    login_as(1)
    response = client.post(f"/gardens/{garden_id}/containers/{container_id}/delete", follow_redirects=True)

    assert response.status_code == 200
    with app.app_context():
        assert Container.query.count() == 0
        assert Planting.query.count() == 0
        assert PlantingLocation.query.count() == 0


def test_delete_container_404s_for_non_owner(app, client, login_as):
    garden_id, area_id = _make_garden_with_area(app, owner_id=1)
    container_id = _make_container(app, area_id)
    login_as(2)

    response = client.post(f"/gardens/{garden_id}/containers/{container_id}/delete")

    assert response.status_code == 404
    with app.app_context():
        assert Container.query.count() == 1

from extensions import db
from models import Container, Garden, GardenArea, Planting, PlantingLocation


def _make_garden(app, owner_id=1):
    with app.app_context():
        garden = Garden(owner_id=owner_id, name="G")
        db.session.add(garden)
        db.session.commit()
        return garden.id


def test_create_area(app, client, login_as):
    garden_id = _make_garden(app)
    login_as(1)

    response = client.post(
        f"/gardens/{garden_id}/areas",
        data={"name": "North bed", "area_type": "bed", "pos_x": "1", "pos_y": "2", "width": "3", "length": "4"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"North bed" in response.data
    with app.app_context():
        area = GardenArea.query.filter_by(garden_id=garden_id).one()
        assert area.pos_x == 1.0
        assert area.width == 3.0


def test_create_area_requires_name(app, client, login_as):
    garden_id = _make_garden(app)
    login_as(1)

    response = client.post(f"/gardens/{garden_id}/areas", data={"name": "", "area_type": "bed"}, follow_redirects=True)

    assert response.status_code == 200
    with app.app_context():
        assert GardenArea.query.count() == 0


def test_create_area_rejects_invalid_type(app, client, login_as):
    garden_id = _make_garden(app)
    login_as(1)

    client.post(f"/gardens/{garden_id}/areas", data={"name": "Bed", "area_type": "not-a-real-type"})

    with app.app_context():
        assert GardenArea.query.count() == 0


def test_create_area_404s_for_non_owner(app, client, login_as):
    garden_id = _make_garden(app, owner_id=1)
    login_as(2)

    response = client.post(f"/gardens/{garden_id}/areas", data={"name": "Sneaky bed", "area_type": "bed"})

    assert response.status_code == 404
    with app.app_context():
        assert GardenArea.query.count() == 0


def _make_area(app, garden_id):
    with app.app_context():
        area = GardenArea(garden_id=garden_id, name="North bed", area_type="bed")
        db.session.add(area)
        db.session.commit()
        return area.id


def test_view_area(app, client, login_as):
    garden_id = _make_garden(app)
    area_id = _make_area(app, garden_id)
    login_as(1)

    response = client.get(f"/gardens/{garden_id}/areas/{area_id}")

    assert response.status_code == 200
    assert b"North bed" in response.data


def test_view_area_404s_for_non_owner(app, client, login_as):
    garden_id = _make_garden(app, owner_id=1)
    area_id = _make_area(app, garden_id)
    login_as(2)

    assert client.get(f"/gardens/{garden_id}/areas/{area_id}").status_code == 404


def test_edit_area(app, client, login_as):
    garden_id = _make_garden(app)
    area_id = _make_area(app, garden_id)
    login_as(1)

    response = client.post(
        f"/gardens/{garden_id}/areas/{area_id}/edit",
        data={"name": "Renamed bed", "area_type": "plot", "pos_x": "5", "pos_y": "5", "width": "2", "length": "2"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    with app.app_context():
        area = db.session.get(GardenArea, area_id)
        assert area.name == "Renamed bed"
        assert area.area_type == "plot"


def test_edit_area_404s_for_non_owner(app, client, login_as):
    garden_id = _make_garden(app, owner_id=1)
    area_id = _make_area(app, garden_id)
    login_as(2)

    response = client.post(f"/gardens/{garden_id}/areas/{area_id}/edit", data={"name": "Hacked", "area_type": "bed"})

    assert response.status_code == 404


def test_delete_area(app, client, login_as):
    garden_id = _make_garden(app)
    area_id = _make_area(app, garden_id)
    login_as(1)

    response = client.post(f"/gardens/{garden_id}/areas/{area_id}/delete", follow_redirects=True)

    assert response.status_code == 200
    with app.app_context():
        assert GardenArea.query.count() == 0


def test_delete_area_cascades_containers_and_nested_plantings(app, client, login_as):
    """Regression test: deleting an area must also delete plantings sitting in its
    containers, not just the area's own PlantingLocation rows (see garden_areas.py's
    _delete_plantings_in_area for why this isn't automatic via ORM cascades alone)."""
    garden_id = _make_garden(app)
    area_id = _make_area(app, garden_id)
    with app.app_context():
        container = Container(garden_area_id=area_id, name="Pot")
        db.session.add(container)
        db.session.commit()
        container_id = container.id

        area_planting = Planting(garden_id=garden_id, crop_name="Tomato")
        container_planting = Planting(garden_id=garden_id, crop_name="Basil")
        db.session.add_all([area_planting, container_planting])
        db.session.commit()
        db.session.add(PlantingLocation(planting_id=area_planting.id, garden_area_id=area_id))
        db.session.add(PlantingLocation(planting_id=container_planting.id, container_id=container_id))
        db.session.commit()

    login_as(1)
    response = client.post(f"/gardens/{garden_id}/areas/{area_id}/delete", follow_redirects=True)

    assert response.status_code == 200
    with app.app_context():
        assert GardenArea.query.count() == 0
        assert Container.query.count() == 0
        assert Planting.query.count() == 0
        assert PlantingLocation.query.count() == 0


def test_delete_area_404s_for_non_owner(app, client, login_as):
    garden_id = _make_garden(app, owner_id=1)
    area_id = _make_area(app, garden_id)
    login_as(2)

    response = client.post(f"/gardens/{garden_id}/areas/{area_id}/delete")

    assert response.status_code == 404
    with app.app_context():
        assert GardenArea.query.count() == 1

from extensions import db
from models import Container, Garden, GardenArea, Planting


def _make_garden_with_area_and_container(app, owner_id=1):
    with app.app_context():
        garden = Garden(owner_id=owner_id, name="G")
        db.session.add(garden)
        db.session.commit()
        area = GardenArea(garden_id=garden.id, name="North bed", area_type="bed")
        db.session.add(area)
        db.session.commit()
        container = Container(garden_area_id=area.id, name="Pot A")
        db.session.add(container)
        db.session.commit()
        return garden.id, area.id, container.id


def test_create_planting_in_area(app, client, login_as):
    garden_id, area_id, _ = _make_garden_with_area_and_container(app)
    login_as(1)

    response = client.post(
        f"/gardens/{garden_id}/plantings",
        data={
            "crop_name": "Tomato",
            "quantity": "3",
            "garden_area_id": str(area_id),
            "container_id": "",
            "pos_x": "0",
            "pos_y": "0",
            "lifecycle_state": "sown",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Tomato" in response.data
    with app.app_context():
        planting = Planting.query.filter_by(garden_id=garden_id).one()
        assert planting.quantity == 3
        assert planting.location.garden_area_id == area_id
        assert planting.location.container_id is None


def test_create_planting_in_container(app, client, login_as):
    garden_id, _, container_id = _make_garden_with_area_and_container(app)
    login_as(1)

    client.post(
        f"/gardens/{garden_id}/plantings",
        data={
            "crop_name": "Basil",
            "quantity": "1",
            "garden_area_id": "",
            "container_id": str(container_id),
            "lifecycle_state": "planned",
        },
    )

    with app.app_context():
        planting = Planting.query.filter_by(garden_id=garden_id).one()
        assert planting.location.container_id == container_id


def test_create_planting_rejects_neither_location(app, client, login_as):
    garden_id, _, _ = _make_garden_with_area_and_container(app)
    login_as(1)

    client.post(
        f"/gardens/{garden_id}/plantings",
        data={"crop_name": "Basil", "garden_area_id": "", "container_id": "", "lifecycle_state": "planned"},
    )

    with app.app_context():
        assert Planting.query.count() == 0


def test_create_planting_rejects_both_locations(app, client, login_as):
    garden_id, area_id, container_id = _make_garden_with_area_and_container(app)
    login_as(1)

    client.post(
        f"/gardens/{garden_id}/plantings",
        data={
            "crop_name": "Basil",
            "garden_area_id": str(area_id),
            "container_id": str(container_id),
            "lifecycle_state": "planned",
        },
    )

    with app.app_context():
        assert Planting.query.count() == 0


def test_create_planting_404s_for_non_owner(app, client, login_as):
    garden_id, area_id, _ = _make_garden_with_area_and_container(app, owner_id=1)
    login_as(2)

    response = client.post(
        f"/gardens/{garden_id}/plantings",
        data={"crop_name": "Sneaky", "garden_area_id": str(area_id), "container_id": "", "lifecycle_state": "planned"},
    )

    assert response.status_code == 404


def _make_planting_in_area(app, garden_id, area_id):
    with app.app_context():
        planting = Planting(garden_id=garden_id, crop_name="Tomato")
        db.session.add(planting)
        db.session.commit()
        from models import PlantingLocation

        db.session.add(PlantingLocation(planting_id=planting.id, garden_area_id=area_id))
        db.session.commit()
        return planting.id


def test_view_planting_404s_for_non_owner(app, client, login_as):
    garden_id, area_id, _ = _make_garden_with_area_and_container(app, owner_id=1)
    planting_id = _make_planting_in_area(app, garden_id, area_id)
    login_as(2)

    assert client.get(f"/gardens/{garden_id}/plantings/{planting_id}").status_code == 404


def test_edit_planting_moves_to_container(app, client, login_as):
    garden_id, area_id, container_id = _make_garden_with_area_and_container(app)
    planting_id = _make_planting_in_area(app, garden_id, area_id)
    login_as(1)

    response = client.post(
        f"/gardens/{garden_id}/plantings/{planting_id}/edit",
        data={
            "crop_name": "Tomato",
            "quantity": "1",
            "garden_area_id": "",
            "container_id": str(container_id),
            "lifecycle_state": "growing",
            "pos_x": "1",
            "pos_y": "1",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    with app.app_context():
        planting = db.session.get(Planting, planting_id)
        assert planting.lifecycle_state == "growing"
        assert planting.location.container_id == container_id
        assert planting.location.garden_area_id is None


def test_delete_planting(app, client, login_as):
    garden_id, area_id, _ = _make_garden_with_area_and_container(app)
    planting_id = _make_planting_in_area(app, garden_id, area_id)
    login_as(1)

    response = client.post(f"/gardens/{garden_id}/plantings/{planting_id}/delete", follow_redirects=True)

    assert response.status_code == 200
    with app.app_context():
        assert Planting.query.count() == 0


def test_delete_planting_404s_for_non_owner(app, client, login_as):
    garden_id, area_id, _ = _make_garden_with_area_and_container(app, owner_id=1)
    planting_id = _make_planting_in_area(app, garden_id, area_id)
    login_as(2)

    response = client.post(f"/gardens/{garden_id}/plantings/{planting_id}/delete")

    assert response.status_code == 404
    with app.app_context():
        assert Planting.query.count() == 1

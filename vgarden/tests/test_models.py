import pytest
from sqlalchemy.exc import IntegrityError

from extensions import db
from models import Container, Garden, GardenArea, Planting, PlantingLocation


def _make_garden_area(garden_id: int) -> GardenArea:
    area = GardenArea(garden_id=garden_id, name="North bed", area_type="bed")
    db.session.add(area)
    db.session.commit()
    return area


def test_planting_location_requires_exactly_one_parent(app):
    with app.app_context():
        garden = Garden(owner_id=1, name="G")
        db.session.add(garden)
        db.session.commit()
        area = _make_garden_area(garden.id)
        planting = Planting(garden_id=garden.id, crop_name="Tomato")
        db.session.add(planting)
        db.session.commit()

        # neither area nor container set
        db.session.add(PlantingLocation(planting_id=planting.id))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()

        # both set
        container = Container(garden_area_id=area.id, name="Pot")
        db.session.add(container)
        db.session.commit()
        db.session.add(
            PlantingLocation(planting_id=planting.id, garden_area_id=area.id, container_id=container.id)
        )
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()

        # exactly one set - succeeds
        db.session.add(PlantingLocation(planting_id=planting.id, garden_area_id=area.id))
        db.session.commit()
        assert planting.location.garden_area_id == area.id


def test_deleting_garden_cascades_areas_containers_plantings(app):
    with app.app_context():
        garden = Garden(owner_id=1, name="G")
        db.session.add(garden)
        db.session.commit()
        area = _make_garden_area(garden.id)
        container = Container(garden_area_id=area.id, name="Pot")
        db.session.add(container)
        db.session.commit()
        planting = Planting(garden_id=garden.id, crop_name="Tomato")
        db.session.add(planting)
        db.session.commit()
        db.session.add(PlantingLocation(planting_id=planting.id, container_id=container.id))
        db.session.commit()

        db.session.delete(garden)
        db.session.commit()

        assert GardenArea.query.count() == 0
        assert Container.query.count() == 0
        assert Planting.query.count() == 0
        assert PlantingLocation.query.count() == 0

import runpy
import sqlite3
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from werkzeug.datastructures import MultiDict

from app import create_app
from extensions import db
from import_notion import import_notion, seed_estimates
from models import PlantReference, RotationGroup, PlantCompanion, PlantFunctionTag
from planning import calculate, parse_details


@pytest.fixture
def app(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "WTF_CSRF_ENABLED": False,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'test.db'}",
            "PLANT_IMAGE_FOLDER": str(tmp_path / "images"),
        }
    )

    class Auth:
        def current_user(self, cookies):
            return {"id": 1}

    app.extensions["auth_client"] = Auth()
    with app.app_context():
        yield app


def test_calculator_rounds_up_and_uses_both_spacings(app):
    plant = PlantReference.query.first()
    plant.yield_qty, plant.yield_unit = 1.5, "kg"
    plant.in_row_spacing_cm, plant.row_spacing_cm = 25, 40
    result = calculate(plant, "10", "kg")
    assert result["plants"] == 7
    assert result["area_m2"] == pytest.approx(0.7)
    for amount, unit in [("0", "kg"), ("NaN", "kg"), ("inf", "kg"), ("10", "fruit")]:
        with pytest.raises(ValueError):
            calculate(plant, amount, unit)
    plant.row_spacing_cm = None
    with pytest.raises(ValueError, match="both"):
        calculate(plant, "10", "kg")


@pytest.mark.parametrize(
    "fields",
    [
        {"yield_qty": "0", "yield_unit": "kg"},
        {"yield_qty": "2"},
        {"in_row_spacing_cm": "nan"},
        {"succession_interval_days": "1.5"},
        {"soil_ph_min": "8", "soil_ph_max": "6"},
        {"soil_ph_max": "15"},
        {"forest_layer": "unknown"},
        {"rotation_group_id": "9999"},
    ],
)
def test_invalid_details_rejected(app, fields):
    with pytest.raises(ValueError):
        parse_details(MultiDict(fields))


def test_import_and_estimates_preserve_source_and_user_edits(app):
    assert import_notion() == (26, 1)
    assert seed_estimates() == 27
    lettuce = PlantReference.query.filter_by(slug="lettuce").one()
    assert lettuce.in_row_spacing_cm == 30
    assert lettuce.yield_qty == 1
    assert "yield_qty" in lettuce.estimated_fields
    assert "in_row_spacing_cm" not in lettuce.estimated_fields
    lettuce.yield_qty = 2
    db.session.commit()
    assert import_notion() == (0, 0)
    assert seed_estimates() == 0
    assert lettuce.yield_qty == 2
    assert RotationGroup.query.count() == 8
    assert {g.name for g in RotationGroup.query.filter_by(is_rotation_exempt=True)} == {
        "Anywhere",
        "Perennials",
    }


def test_form_api_and_guild_round_trip(app):
    client = app.test_client()
    group = RotationGroup.query.filter_by(name="Solanums").one()
    fields = {
        "common_name": "Test crop",
        "scientific_name": "Example species",
        "yield_qty": "1.5",
        "yield_unit": "kg",
        "in_row_spacing_cm": "25",
        "row_spacing_cm": "40",
        "soil_ph_min": "6",
        "soil_ph_max": "7",
        "rotation_group_id": str(group.id),
        "uses_present": "1",
        "uses": ["culinary", "ornamental"],
        "pests_present": "1",
        "pests": "Aphids, Aphids",
        "forest_layer": "herbaceous",
    }
    response = client.post("/plants", data=fields, follow_redirects=True)
    assert response.status_code == 200
    payload = client.get("/api/plants/test-crop").json
    assert payload["yield_qty"] == 1.5
    assert sorted(payload["uses"]) == ["culinary", "ornamental"]
    assert payload["pests"] == ["Aphids"]
    assert payload["plants_per_m2"] == 10
    assert client.get("/plants/test-crop/edit").status_code == 200
    assert b"7" in client.get("/plants/test-crop/calculate?amount=10&unit=kg").data
    assert client.get("/plants/test-crop/calculate?amount=10&unit=fruit").status_code == 400
    companion = PlantReference.query.filter_by(slug="tomato").one()
    function = PlantFunctionTag.query.first()
    assert (
        client.post(
            "/plants/test-crop/guild",
            data={"companion_id": companion.id, "function_id": function.id},
        ).status_code
        == 302
    )
    assert PlantCompanion.query.count() == 1
    assert client.delete("/api/plants/tomato").status_code == 204
    assert PlantCompanion.query.count() == 0


def test_upgrade_preserves_legacy_rows_and_maps_rotation(tmp_path):
    path = tmp_path / "legacy.db"
    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            runpy.run_path(str(Path(__file__).resolve().parents[1] / "migrations/versions/001_baseline.py"))["upgrade"]()
        conn.execute(text("ALTER TABLE plant_references ADD COLUMN rotation_group TEXT"))
        conn.execute(
            text(
                "INSERT INTO plant_references (id, slug, common_name, scientific_name, family, summary, rotation_group) VALUES (99,'legacy','Legacy','Legacy species','','Original wording',' brassica ')"
            )
        )
        conn.execute(
            text("INSERT INTO planting_months (plant_reference_id,month_number) VALUES (99,3)")
        )
        conn.execute(
            text(
                "INSERT INTO plant_images (plant_reference_id,filename) VALUES (99,'original.png')"
            )
        )
    app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{path}",
            "PLANT_IMAGE_FOLDER": str(tmp_path / "images"),
        }
    )
    with app.app_context():
        plant = db.session.get(PlantReference, 99)
        assert plant.summary == "Original wording"
        assert plant.rotation_group.name == "Brassicas"
        assert plant.yield_qty is None
        assert plant.image.filename == "original.png"
        assert plant.planting_months[0].month_number == 3
        assert db.session.execute(text("SELECT version_num FROM alembic_version")).scalar() == "003"
        assert any(
            c["name"] == "ck_yield_qty_positive"
            for c in inspect(db.engine).get_check_constraints("plant_references")
        )
    with sqlite3.connect(path) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE plant_references SET in_row_spacing_cm=-1 WHERE id=99")


def test_api_partial_update_preserves_and_validates_details(app):
    client = app.test_client()
    assert client.patch('/api/plants/tomato', json={'yield_qty':2,'yield_unit':'kg','soil_ph_min':6,'soil_ph_max':7,'uses':['culinary'],'pests':['Aphids']}).status_code == 200
    assert client.patch('/api/plants/tomato', json={'soil_ph_min':8}).status_code == 400
    response = client.patch('/api/plants/tomato', json={'yield_qty':3})
    assert response.status_code == 200
    assert response.json['yield_qty'] == 3
    assert response.json['yield_unit'] == 'kg'
    assert response.json['pests'] == ['Aphids']
    assert response.json['common_name'] == 'Tomato'

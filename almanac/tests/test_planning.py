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
from models import (
    Disease, Pest, PlantReference, RotationGroup, PlantCompanion, PlantFunctionTag,
    PlantImage, PlantUse, PlantingMonth,
)
from growing_details import parse_details
from public_seed import import_snapshot


def _public_snapshot():
    return {
        "snapshot_format": 1,
        "tables": {
            "rotation_groups": [
                {"id": 1, "name": "Solanums", "feeder_weight": "heavy", "is_rotation_exempt": 0}
            ],
            "pests": [{"id": 1, "name": "Aphids", "description": "Sap-feeding insects."}],
            "diseases": [{"id": 1, "name": "Wilt", "description": "A test disease."}],
            "function_tags": [
                {"id": 1, "name": "pollinator", "description": "Supports pollinators."}
            ],
            "uses": [{"id": 1, "name": "culinary", "description": "Used as food."}],
            "plant_references": [
                {
                    "id": 10, "slug": "test-tomato", "common_name": "Test Tomato",
                    "scientific_name": "Solanum test", "family": "Solanaceae",
                    "summary": "A public test plant.", "rotation_group_id": 1,
                },
                {
                    "id": 11, "slug": "test-basil", "common_name": "Test Basil",
                    "scientific_name": "Ocimum test", "family": "Lamiaceae",
                    "summary": "A companion test plant.", "rotation_group_id": None,
                },
            ],
            "planting_months": [
                {"plant_reference_id": 10, "month_number": 9},
                {"plant_reference_id": 11, "month_number": 10},
            ],
            "plant_pests": [{"plant_id": 10, "tag_id": 1}],
            "plant_diseases": [{"plant_id": 10, "tag_id": 1}],
            "plant_function_tags": [{"plant_id": 11, "tag_id": 1}],
            "plant_uses": [{"plant_id": 10, "tag_id": 1}],
            "plant_companions": [
                {"plant_id": 10, "companion_id": 11, "function_id": 1, "notes": "Test link."}
            ],
            "plant_images": [
                {"plant_reference_id": 10, "filename": "test-tomato.jpg"},
            ],
        },
    }


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


def test_harvest_space_calculator_is_not_exposed(app):
    client = app.test_client()
    page = client.get("/plants/lettuce")
    assert page.status_code == 200
    assert b"How much growing space?" not in page.data
    assert b"Target harvest" not in page.data
    assert b"Soil &amp; care" in page.data or b"Soil & care" in page.data
    assert client.get("/plants/lettuce/calculate?amount=10&unit=head").status_code == 404


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


def test_controlled_vocabulary_is_seeded(app):
    assert RotationGroup.query.count() == 8
    assert {g.name for g in RotationGroup.query.filter_by(is_rotation_exempt=True)} == {
        "Anywhere",
        "Perennials",
    }


def test_public_snapshot_imports_relationships_and_never_overwrites(tmp_path, monkeypatch):
    monkeypatch.setattr("app.fetch_snapshot", lambda _url, _timeout: _public_snapshot())
    seeded = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'public-seed.db'}",
            "PLANT_IMAGE_FOLDER": str(tmp_path / "images"),
            "LOAD_MY_GARDEN_SEED": True,
            "MY_GARDEN_IMAGE_BASE_URL": "https://images.example/",
        }
    )
    with seeded.app_context():
        assert PlantReference.query.count() == 2
        tomato = PlantReference.query.filter_by(slug="test-tomato").one()
        assert [month.month_number for month in tomato.planting_months] == [9]
        assert [pest.name for pest in tomato.pests] == ["Aphids"]
        assert [disease.name for disease in tomato.diseases] == ["Wilt"]
        assert [use.name for use in tomato.uses] == ["culinary"]
        assert tomato.guild_links[0].companion.slug == "test-basil"
        assert tomato.image.public_url == "https://images.example/test-tomato.jpg"
        assert b"https://images.example/test-tomato.jpg" in seeded.test_client().get("/").data

        tomato.summary = "My local edit"
        db.session.commit()
        assert import_snapshot(_public_snapshot(), "https://images.example/") == 0
        assert tomato.summary == "My local edit"


def test_public_snapshot_failure_falls_back_to_builtin_seed(tmp_path, monkeypatch):
    def unavailable(_url, _timeout):
        raise OSError("offline")

    monkeypatch.setattr("app.fetch_snapshot", unavailable)
    seeded = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'fallback-seed.db'}",
            "PLANT_IMAGE_FOLDER": str(tmp_path / "images"),
            "LOAD_MY_GARDEN_SEED": True,
        }
    )
    with seeded.app_context():
        assert PlantReference.query.count() == 8


def test_add_missing_preserves_local_records_and_remaps_snapshot_ids(app):
    basil = PlantReference.query.filter_by(slug="basil").one()
    basil.summary = "My own basil notes"
    basil.water_needs = "low"
    basil.soil_ph_min = 0
    basil.care_notes = None
    basil.uses_notes = ""
    basil.image = PlantImage(filename="local-basil.jpg", public_url=None)
    local_pest = Pest(name="Local beetle", description="My observation")
    basil.pests = [local_pest]
    aphids = Pest(name="Aphids", description="My edited aphid description")
    wilt = Disease(name="Wilt", description="My edited wilt description")
    function = PlantFunctionTag(name="pollinator", description="My edited function")
    culinary = PlantUse.query.filter_by(name="culinary").one()
    culinary.description = "My edited use"
    group = RotationGroup.query.filter_by(name="Solanums").one()
    group.feeder_weight = "light"
    basil.rotation_group = group
    db.session.add_all([aphids, wilt, function])
    db.session.flush()
    basil.guild_links.append(PlantCompanion(
        companion_id=PlantReference.query.filter_by(slug="carrot").one().id,
        function_id=function.id, notes="My saved companion",
    ))
    db.session.commit()
    original_values = {
        column.name: getattr(basil, column.name) for column in PlantReference.__table__.columns
        if getattr(basil, column.name) not in (None, "")
    }
    original_months = [(month.id, month.month_number) for month in basil.planting_months]
    original_image_id = basil.image.id

    snapshot = _public_snapshot()
    tables = snapshot["tables"]
    tables["plant_references"][1].update(
        slug="basil", water_needs="high", soil_ph_min=6, soil_ph_max=7,
        care_notes="Public care guidance", uses_notes="Public use guidance",
    )
    tables["rotation_groups"][0]["is_rotation_exempt"] = 1
    tables["planting_months"].append({"plant_reference_id": 11, "month_number": 3})
    for table in ("plant_pests", "plant_diseases", "plant_function_tags", "plant_uses"):
        tables[table].append({"plant_id": 11, "tag_id": 1})
    tables["plant_companions"].append({
        "plant_id": 11, "companion_id": 10, "function_id": 1, "notes": "Imported companion",
    })
    tables["plant_images"].append({
        "plant_reference_id": 11, "filename": "replacement-basil.jpg",
    })

    assert import_snapshot(snapshot, "https://images.example/", add_missing=True) == 1
    assert PlantReference.query.count() == 9
    assert all(getattr(basil, field) == value for field, value in original_values.items())
    assert basil.care_notes == "Public care guidance"
    assert basil.uses_notes == "Public use guidance"
    assert basil.soil_ph_min == 0 and basil.soil_ph_max == 7
    assert set(original_months) <= {(m.id, m.month_number) for m in basil.planting_months}
    assert 3 in [m.month_number for m in basil.planting_months]
    assert {pest.name for pest in basil.pests} == {"Local beetle", "Aphids"}
    assert basil.diseases == [wilt]
    assert basil.function_tags == [function]
    assert basil.uses == [culinary]
    assert {(link.companion.slug, link.notes) for link in basil.guild_links} == {
        ("carrot", "My saved companion"), ("test-tomato", "Imported companion"),
    }
    assert basil.image.id == original_image_id
    assert basil.image.filename == "local-basil.jpg"
    assert basil.image.public_url is None
    assert aphids.description == "My edited aphid description"
    assert wilt.description == "My edited wilt description"
    assert function.description == "My edited function"
    assert culinary.description == "My edited use"

    tomato = PlantReference.query.filter_by(slug="test-tomato").one()
    assert tomato.id != 10 and basil.id != 11
    assert tomato.rotation_group_id == group.id and group.id != 1
    assert tomato.rotation_group.feeder_weight == "light"
    assert tomato.rotation_group.is_rotation_exempt is False
    assert tomato.pests == [aphids]
    assert tomato.diseases == [wilt]
    assert tomato.uses == [culinary]
    assert [month.month_number for month in tomato.planting_months] == [9]
    assert tomato.guild_links[0].companion_id == basil.id
    assert tomato.guild_links[0].function_id == function.id
    assert tomato.image.public_url == "https://images.example/test-tomato.jpg"

    counts = [model.query.count() for model in (
        PlantReference, PlantingMonth, PlantCompanion, PlantImage, Pest, Disease,
        PlantFunctionTag, PlantUse, RotationGroup,
    )]
    merged_basil = basil.to_dict()
    tables["plant_companions"][-1]["notes"] = "Do not overwrite existing notes"
    assert import_snapshot(snapshot, "https://images.example/", add_missing=True) == 0
    assert counts == [model.query.count() for model in (
        PlantReference, PlantingMonth, PlantCompanion, PlantImage, Pest, Disease,
        PlantFunctionTag, PlantUse, RotationGroup,
    )]
    assert basil.to_dict() == merged_basil
    assert len(tomato.pests) == len(tomato.diseases) == len(tomato.uses) == 1


def test_import_my_garden_cli_uses_configured_source_and_is_repeatable(app, monkeypatch):
    calls = []

    def snapshot(url, timeout):
        calls.append((url, timeout))
        return _public_snapshot()

    monkeypatch.setattr("app.fetch_snapshot", snapshot)
    app.config.update(MY_GARDEN_SEED_URL="https://example.test/catalogue.json",
                      MY_GARDEN_SEED_TIMEOUT=7)
    runner = app.test_cli_runner()
    result = runner.invoke(args=["import-my-garden"])
    assert result.exit_code == 0, result.output
    assert "Added 2 My Garden plants" in result.output
    assert calls == [("https://example.test/catalogue.json", 7)]
    assert PlantReference.query.count() == 10
    result = runner.invoke(args=["import-my-garden"])
    assert result.exit_code == 0
    assert "Added 0 My Garden plants" in result.output
    assert PlantReference.query.count() == 10


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
    assert "plants_per_m2" not in payload
    assert client.get("/plants/test-crop/edit").status_code == 200
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
            runpy.run_path(
                str(Path(__file__).resolve().parents[1] / "migrations/versions/001_baseline.py")
            )["upgrade"]()
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
        assert db.session.execute(text("SELECT version_num FROM alembic_version")).scalar() == "004"
        assert any(
            c["name"] == "ck_yield_qty_positive"
            for c in inspect(db.engine).get_check_constraints("plant_references")
        )
    with sqlite3.connect(path) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE plant_references SET in_row_spacing_cm=-1 WHERE id=99")


def test_api_partial_update_preserves_and_validates_details(app):
    client = app.test_client()
    assert (
        client.patch(
            "/api/plants/tomato",
            json={
                "yield_qty": 2,
                "yield_unit": "kg",
                "soil_ph_min": 6,
                "soil_ph_max": 7,
                "uses": ["culinary"],
                "pests": ["Aphids"],
            },
        ).status_code
        == 200
    )
    assert client.patch("/api/plants/tomato", json={"soil_ph_min": 8}).status_code == 400
    response = client.patch("/api/plants/tomato", json={"yield_qty": 3})
    assert response.status_code == 200
    assert response.json["yield_qty"] == 3
    assert response.json["yield_unit"] == "kg"
    assert response.json["pests"] == ["Aphids"]
    assert response.json["common_name"] == "Tomato"


def test_guild_seed_is_repeatable_and_keeps_edited_links(app):
    from garden_data import seed_guilds

    db.session.add_all(
        [
            PlantReference(
                slug="bunching-onion-test",
                common_name="Test onion",
                scientific_name="Allium test",
                family="Amaryllidaceae",
                summary="Test onion.",
            ),
            PlantReference(
                slug="alyssum",
                common_name="Alyssum",
                scientific_name="Lobularia maritima",
                family="Brassicaceae",
                summary="Test companion.",
            ),
            PlantReference(
                slug="marigold-french-marigold",
                common_name="French marigold",
                scientific_name="Tagetes patula",
                family="Asteraceae",
                summary="Test companion.",
            ),
        ]
    )
    db.session.commit()
    assert seed_guilds() > 0
    onion = PlantReference.query.filter_by(slug="bunching-onion-test").one()
    assert {link.companion.slug for link in onion.guild_links} == {
        "alyssum",
        "marigold-french-marigold",
    }
    link = onion.guild_links[0]
    link.notes = "My own planting notes"
    db.session.commit()
    assert seed_guilds() == 0
    assert link.notes == "My own planting notes"
    assert all(link.plant_id != link.companion_id for link in PlantCompanion.query.all())


def test_pest_and_disease_pages_link_back_to_plants(app):
    from garden_data import refresh_garden_wording

    tomato = PlantReference.query.filter_by(slug="tomato").one()
    lettuce = PlantReference.query.filter_by(slug="lettuce").one()
    alyssum = PlantReference(
        slug="alyssum",
        common_name="Sweet Alyssum",
        scientific_name="Lobularia maritima",
        family="Brassicaceae",
        summary="A flowering plant for garden edges.",
    )
    aphids = Pest(name="Aphids")
    slugs = Pest(name="Slugs and snails")
    mildew = Disease(name="Powdery mildew")
    db.session.add_all([alyssum, aphids, slugs, mildew])
    tomato.pests.append(aphids)
    lettuce.pests.extend([aphids, slugs])
    tomato.diseases.append(mildew)
    db.session.commit()

    refresh_garden_wording()
    client = app.test_client()

    pests = client.get("/pests")
    assert pests.status_code == 200
    assert b"Aphids" in pests.data
    assert b"Slugs and snails" in pests.data

    home = client.get("/")
    assert b"Plant problem library" in home.data
    assert b'href="/pests"' in home.data
    assert b'href="/diseases"' in home.data

    plant_page = client.get(f"/plants/{tomato.slug}")
    assert 1 < len(aphids.plants) < PlantReference.query.count()
    assert f"/pests/{aphids.id}".encode() in plant_page.data

    detail = client.get(f"/pests/{aphids.id}")
    assert detail.status_code == 200
    assert b"Use the lightest effective response" in detail.data
    assert b"Sweet Alyssum" in detail.data
    assert b"Nasturtium" in detail.data
    assert b"insecticidal soap" in detail.data
    assert b'href="/plants/alyssum"' in detail.data
    assert tomato.common_name.encode() in detail.data

    diseases = client.get("/diseases")
    assert diseases.status_code == 200
    assert b"Powdery mildew" in diseases.data
    disease_detail = client.get(f"/diseases/{mildew.id}")
    assert disease_detail.status_code == 200
    assert b"Make the garden less inviting" in disease_detail.data
    assert b"Choose a labelled treatment" in disease_detail.data
    assert b"horticultural oil" in disease_detail.data
    assert client.get("/pests/999999").status_code == 404


def test_refresh_updates_old_problem_copy_but_preserves_custom_descriptions(app):
    from garden_data import LEGACY_PROBLEM_DESCRIPTIONS, PROBLEM_DESCRIPTIONS
    from garden_data import refresh_garden_wording

    mildew = Disease(name="Powdery mildew")
    db.session.add(mildew)
    mildew.description = LEGACY_PROBLEM_DESCRIPTIONS["Powdery mildew"]
    db.session.commit()
    refresh_garden_wording()
    assert mildew.description == PROBLEM_DESCRIPTIONS["Powdery mildew"]
    mildew.description = "My local observations and management notes"
    db.session.commit()
    refresh_garden_wording()
    assert mildew.description == "My local observations and management notes"
    assert refresh_garden_wording() == 0

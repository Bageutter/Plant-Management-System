"""Schema migrations (Flask-Migrate / Alembic) for the Virtual Garden service (issue #10)."""

from __future__ import annotations

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

from conftest import TestConfig


def _revision(app):
    from extensions import db

    with app.app_context():
        return db.session.execute(text("SELECT version_num FROM alembic_version")).scalar()


def test_fresh_database_is_at_head_and_matches_the_models(app):
    from extensions import db

    with app.app_context():
        config = app.extensions["migrate"].migrate.get_config()
    head = ScriptDirectory.from_config(config).get_current_head()
    assert _revision(app) == head == "0001"
    with app.app_context(), db.engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        assert compare_metadata(context, db.metadata) == []


def test_create_all_era_database_is_adopted_with_its_rows(tmp_path):
    """The previous build used db.create_all(). Older databases also predate the two
    AI tables, which create_all() added on the next start; adoption must do the same."""

    import app as app_module
    from extensions import db

    path = tmp_path / "legacy.db"
    engine = create_engine(f"sqlite:///{path}")
    import models  # noqa: F401 - registers every table on db.metadata

    older = [
        t for name, t in db.metadata.tables.items()
        if name not in ("garden_chat_messages", "garden_ai_loop_runs")
    ]
    db.metadata.create_all(engine, tables=older)
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO gardens (id, owner_id, name, description, location_label, climate_zone, "
            "map_width_m, map_height_m) VALUES (1, 7, 'Back yard', '', 'Sydney', '', 10.0, 10.0)"
        ))
        connection.execute(text(
            "INSERT INTO garden_areas (id, garden_id, name, area_type, pos_x, pos_y, width, length) "
            "VALUES (1, 1, 'North bed', 'bed', 0, 0, 2, 1)"
        ))
        connection.execute(text(
            "INSERT INTO plantings (id, garden_id, crop_name, quantity, lifecycle_state) "
            "VALUES (1, 1, 'Tomato', 3, 'growing')"
        ))
    engine.dispose()
    assert "garden_ai_loop_runs" not in inspect(create_engine(f"sqlite:///{path}")).get_table_names()

    class Config(TestConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{path}"
        AI_LOOP_LOG_DIR = str(tmp_path / "logs")

    app = app_module.create_app(Config)

    assert _revision(app) == "0001"
    with app.app_context():
        from models import Garden

        garden = db.session.get(Garden, 1)
        assert garden.name == "Back yard" and garden.owner_id == 7
        assert [a.name for a in garden.areas] == ["North bed"]
        assert [p.crop_name for p in garden.plantings] == ["Tomato"]
        tables = set(inspect(db.engine).get_table_names())
        assert {"garden_chat_messages", "garden_ai_loop_runs", "alembic_version"} <= tables
        # ...and the adopted database now matches the models exactly.
        with db.engine.connect() as connection:
            context = MigrationContext.configure(connection, opts={"compare_type": True})
            assert compare_metadata(context, db.metadata) == []


def test_auto_migrate_off_leaves_the_schema_to_the_cli(tmp_path):
    import app as app_module
    from extensions import db

    class Config(TestConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'manual.db'}"
        AI_LOOP_LOG_DIR = str(tmp_path / "logs")
        AUTO_MIGRATE = False

    app = app_module.create_app(Config)
    with app.app_context():
        assert inspect(db.engine).get_table_names() == []
    result = app.test_cli_runner().invoke(args=["db", "upgrade"])
    assert result.exit_code == 0, result.output
    assert _revision(app) == "0001"

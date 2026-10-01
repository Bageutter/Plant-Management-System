"""Schema migrations (Flask-Migrate / Alembic) for the health service.

Covers the acceptance criteria of issue #10: a fresh database lands at head and
matches the models exactly; databases from every earlier build are adopted and
upgraded with their rows intact; legacy float confidences are normalised.
"""

from __future__ import annotations

import os
import sqlite3

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory

from conftest import FakeOllama, TestConfig, make_assessment

LEGACY_SCHEMA = """
CREATE TABLE assessments (
    id INTEGER NOT NULL PRIMARY KEY,
    plant_ref VARCHAR(200),
    description TEXT,
    has_image BOOLEAN NOT NULL,
    image_mime VARCHAR(64),
    model VARCHAR(120) NOT NULL,
    status VARCHAR(20) NOT NULL,
    health_score INTEGER,
    confidence FLOAT,
    plant_identification VARCHAR(200),
    summary TEXT NOT NULL,
    issues_json TEXT NOT NULL,
    recommendations_json TEXT NOT NULL,
    missing_information_json TEXT NOT NULL,
    created_at DATETIME
);
CREATE INDEX ix_assessments_plant_ref ON assessments (plant_ref);
"""

# What the create_all() + startup-ALTER stop-gap (the build before this one) produced.
STOPGAP_EXTRA = """
ALTER TABLE assessments ADD COLUMN image_data BLOB;
ALTER TABLE assessments ADD COLUMN score_band VARCHAR(80);
ALTER TABLE assessments ADD COLUMN confidence_reason TEXT;
ALTER TABLE assessments ADD COLUMN duration_ms INTEGER;
"""

LEGACY_ROWS = [
    # (plant_ref, confidence) — a float from the very first build, a label, a
    # capitalised label, and NULL.
    ("Tomato, back bed", 0.7),
    ("Basil", "medium"),
    ("Chilli", "High"),
    ("Mint", None),
]


def _app_for(db_path):
    from app import create_app

    class Config(TestConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{db_path}"

    app = create_app(Config)
    app.extensions["ollama"] = FakeOllama()
    return app


def _build_legacy_db(path, *, stopgap: bool):
    connection = sqlite3.connect(path)
    connection.executescript(LEGACY_SCHEMA + (STOPGAP_EXTRA if stopgap else ""))
    for index, (plant_ref, confidence) in enumerate(LEGACY_ROWS, start=1):
        connection.execute(
            "INSERT INTO assessments (id, plant_ref, description, has_image, model, status, "
            "health_score, confidence, summary, issues_json, recommendations_json, "
            "missing_information_json, created_at) VALUES (?, ?, ?, 0, 'old-model', 'at_risk', "
            "45, ?, 'Old summary', '[]', '[]', '[]', '2026-01-01 10:00:00')",
            (index, plant_ref, f"Description {index}", confidence),
        )
    connection.commit()
    connection.close()


def _current_revision(app):
    from extensions import db
    from sqlalchemy import text

    with app.app_context():
        return db.session.execute(text("SELECT version_num FROM alembic_version")).scalar()


def _script(app):
    with app.app_context():
        config = app.extensions["migrate"].migrate.get_config()
    return ScriptDirectory.from_config(config)


def _head(app):
    return _script(app).get_current_head()


def _columns(app):
    from extensions import db
    from sqlalchemy import inspect

    with app.app_context():
        return {c["name"]: c for c in inspect(db.engine).get_columns("assessments")}


def test_fresh_database_is_at_head_and_matches_the_models(app):
    from extensions import db

    assert _current_revision(app) == _head(app) == "0005"
    with app.app_context(), db.engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        assert compare_metadata(context, db.metadata) == []


@pytest.mark.parametrize("stopgap", [False, True], ids=["first-build", "startup-alter-stopgap"])
def test_pre_migration_database_is_adopted_and_upgraded_keeping_its_rows(tmp_path, stopgap):
    path = os.path.join(tmp_path, "legacy.db")
    _build_legacy_db(path, stopgap=stopgap)

    app = _app_for(path)

    assert _current_revision(app) == "0005"
    columns = _columns(app)
    assert {"image_data", "score_band", "confidence_reason", "duration_ms"} <= set(columns)
    assert "VARCHAR" in str(columns["confidence"]["type"]).upper()

    client = app.test_client()
    records = client.get("/plant-health-records/assessments").get_json()
    assert [r["plant_ref"] for r in records] == ["Mint", "Chilli", "Basil", "Tomato, back bed"]
    by_ref = {r["plant_ref"]: r for r in records}
    assert by_ref["Tomato, back bed"]["description"] == "Description 1"
    # 0003: the legacy float is cleared, labels are normalised, NULL stays NULL.
    assert by_ref["Tomato, back bed"]["confidence"] is None
    assert by_ref["Basil"]["confidence"] == "medium"
    assert by_ref["Chilli"]["confidence"] == "high"
    assert by_ref["Mint"]["confidence"] is None

    # The upgraded database is fully usable: new records land beside the old ones.
    created = make_assessment(client, plant_ref="New tomato")
    assert created["confidence"] == "medium"
    assert len(client.get("/plant-health-records/assessments").get_json()) == 5

    # 0004: every plant name already recorded is offered as a title.
    titles = [p["name"] for p in client.get("/plant-health-records/plants").get_json()]
    assert titles == ["Basil", "Chilli", "Mint", "New tomato", "Tomato, back bed"]

    # A second start is a no-op (idempotent).
    again = _app_for(path)
    assert _current_revision(again) == "0005"


def test_auto_migrate_can_be_turned_off_for_an_explicit_deploy_step(tmp_path):
    from app import create_app
    from extensions import db
    from sqlalchemy import inspect

    class Config(TestConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{os.path.join(tmp_path, 'manual.db')}"
        AUTO_MIGRATE = False

    app = create_app(Config)
    with app.app_context():
        assert inspect(db.engine).get_table_names() == []

    # ...and `flask db upgrade` (the CLI Flask-Migrate registers) applies them.
    result = app.test_cli_runner().invoke(args=["db", "upgrade"])
    assert result.exit_code == 0, result.output
    assert _current_revision(app) == "0005"


def test_revisions_form_a_single_linear_history(app):
    script = _script(app)
    assert script.get_heads() == ["0005"]
    assert [rev.revision for rev in script.walk_revisions()] == ["0005", "0004", "0003", "0002", "0001"]

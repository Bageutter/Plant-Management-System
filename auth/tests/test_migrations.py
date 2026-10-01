"""Schema migrations (Flask-Migrate / Alembic) for the auth service (issue #10)."""

from __future__ import annotations

import sqlite3

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text

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
    """A database built by the previous build (db.create_all(), no alembic_version)."""

    import app as app_module
    from extensions import db

    path = tmp_path / "legacy.db"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE users (
            id INTEGER NOT NULL PRIMARY KEY,
            email VARCHAR(255) NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            created_at DATETIME
        );
        CREATE UNIQUE INDEX ix_users_email ON users (email);
        CREATE TABLE gardens (
            id INTEGER NOT NULL PRIMARY KEY,
            garden_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            created_at DATETIME,
            FOREIGN KEY(user_id) REFERENCES users (id)
        );
        CREATE UNIQUE INDEX ix_gardens_garden_id ON gardens (garden_id);
        CREATE INDEX ix_gardens_user_id ON gardens (user_id);
        INSERT INTO users (id, email, password_hash, created_at)
            VALUES (1, 'gardener@example.com', 'scrypt:hash', '2026-01-01 10:00:00');
        INSERT INTO gardens (id, garden_id, user_id, created_at) VALUES (1, 42, 1, '2026-01-02 10:00:00');
        """
    )
    connection.commit()
    connection.close()

    class Config(TestConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{path}"

    app = app_module.create_app(Config)

    assert _revision(app) == "0001"
    with app.app_context():
        from models import Garden, User

        user = db.session.get(User, 1)
        assert user.email == "gardener@example.com"
        assert [g.garden_id for g in user.gardens] == [42]
        assert db.session.get(Garden, 1).owner is user
        assert "alembic_version" in inspect(db.engine).get_table_names()

    # Idempotent on the next start.
    assert _revision(app_module.create_app(Config)) == "0001"


def test_auto_migrate_off_leaves_the_schema_to_the_cli(tmp_path):
    import app as app_module
    from extensions import db

    class Config(TestConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'manual.db'}"
        AUTO_MIGRATE = False

    app = app_module.create_app(Config)
    with app.app_context():
        assert inspect(db.engine).get_table_names() == []
    result = app.test_cli_runner().invoke(args=["db", "upgrade"])
    assert result.exit_code == 0, result.output
    assert _revision(app) == "0001"

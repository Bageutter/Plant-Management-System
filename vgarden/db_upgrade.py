"""Apply this service's Alembic migrations (Flask-Migrate) at startup.

``db.create_all()`` used to build the schema. It creates missing tables but
never alters existing ones, so the first model change broke every database
created by an earlier build (issue #10). The schema is now versioned under
``migrations/versions`` and applied with ``flask db upgrade`` -- run here when
the app starts (``AUTO_MIGRATE``, default on), or by hand as a deploy step.

A database from the ``create_all()`` era has the tables but no
``alembic_version``. It is *adopted*: stamped at the baseline revision, which
describes exactly that schema, and then upgraded like any other database, so
existing rows are kept.
"""

from __future__ import annotations

import logging

from alembic import command
from flask import Flask
from sqlalchemy import inspect

from extensions import db

logger = logging.getLogger(__name__)

# The revision that matches a database built by db.create_all() before
# migrations existed, and the tables that revision creates. Never renumber the
# revision, and never add a table introduced by a later revision to this tuple:
# adoption creates any of these an old build lacked, then stamps the baseline.
BASELINE_REVISION = "0001"
BASELINE_TABLES = (
    "gardens",
    "garden_areas",
    "containers",
    "plantings",
    "planting_locations",
    "garden_chat_messages",
    "garden_ai_loop_runs",
)


def upgrade_database(app: Flask) -> None:
    """Bring the configured database up to the latest revision."""

    with app.app_context():
        config = app.extensions["migrate"].migrate.get_config()
        inspector = inspect(db.engine)
        existing = set(inspector.get_table_names())
        if "alembic_version" not in existing and existing & set(BASELINE_TABLES):
            _adopt_unversioned_database(config, existing)
        command.upgrade(config, "head")


def _adopt_unversioned_database(config, existing: set[str]) -> None:
    """Stamp a create_all()-era database at the baseline it already matches.

    create_all() only ever created tables that were missing, so an old database
    may lack a baseline table (one added to the models later, before migrations
    existed). Those are created first, so the stamp is exactly true. Tables from
    later revisions are left to those revisions.
    """

    missing = sorted(set(BASELINE_TABLES) - existing)
    if missing:
        logger.info("Adoption: creating baseline tables the old build never made: %s", ", ".join(missing))
        db.metadata.create_all(bind=db.engine, tables=[db.metadata.tables[name] for name in missing])
    logger.info(
        "Adopting an unversioned database (tables: %s) at revision %s",
        ", ".join(sorted(existing)),
        BASELINE_REVISION,
    )
    command.stamp(config, BASELINE_REVISION)

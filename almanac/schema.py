"""Versioned upgrades for both pre-migration installations and fresh databases."""

from pathlib import Path
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from extensions import db


def upgrade_schema():
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    tables = inspect(db.engine).get_table_names()
    if "plant_references" in tables and "alembic_version" not in tables:
        # The old application used create_all; adopt it without deleting its data.
        command.stamp(config, "001")
    command.upgrade(config, "head")

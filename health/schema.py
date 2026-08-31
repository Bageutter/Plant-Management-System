"""Lightweight schema reconciliation for development databases.

``db.create_all()`` creates missing *tables* but never alters existing ones, so a
database created by an earlier version of the service keeps its old columns and
every query then fails with "no such column".

This project has no migration tool (SQLite is the documented dev default), so on
startup we compare each mapped table with the live database and issue
``ALTER TABLE ... ADD COLUMN`` for anything missing. That covers the only schema
change this service has needed so far — additive, nullable columns.

This is a deliberate stop-gap, not the intended long-term answer: it is additive
only, keeps no history, and silently relaxes NOT NULL when it cannot add a column
safely. Replacing it with Flask-Migrate/Alembic across all services is tracked in
https://github.com/Bageutter/Plant-Management-System/issues/10

It deliberately does not drop or alter existing columns: that needs a real
migration tool, and silently destroying data at startup would be far worse than
leaving a stale column in place.
"""

from __future__ import annotations

import logging

from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)


def sync_schema(db) -> list[str]:
    """Add any mapped columns that are missing from the live database.

    Returns the list of ``table.column`` names that were added.
    """

    engine = db.engine
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    added: list[str] = []

    for table in db.metadata.sorted_tables:
        if table.name not in existing_tables:
            # create_all() handles brand-new tables.
            continue

        present = {col["name"] for col in inspector.get_columns(table.name)}
        missing = [col for col in table.columns if col.name not in present]

        for column in missing:
            ddl = _add_column_ddl(table.name, column, engine)
            if ddl is None:
                logger.warning(
                    "Cannot auto-add column %s.%s; a manual migration is required.",
                    table.name,
                    column.name,
                )
                continue

            try:
                with engine.begin() as connection:
                    connection.execute(text(ddl))
            except SQLAlchemyError:
                logger.exception("Failed adding column %s.%s", table.name, column.name)
                continue

            added.append(f"{table.name}.{column.name}")
            logger.info("Added missing column %s.%s", table.name, column.name)

    return added


def _add_column_ddl(table_name: str, column, engine) -> str | None:
    """Build an ADD COLUMN statement, or None if it cannot be done safely."""

    try:
        column_type = column.type.compile(dialect=engine.dialect)
    except SQLAlchemyError:
        return None

    ddl = f'ALTER TABLE "{table_name}" ADD COLUMN "{column.name}" {column_type}'

    if column.nullable:
        return ddl

    # A NOT NULL column can only be added when existing rows have a value to use.
    default = _literal_default(column)
    if default is None:
        # Fall back to a nullable column rather than failing outright: the data is
        # more valuable than the constraint on a dev database.
        return ddl

    return f"{ddl} NOT NULL DEFAULT {default}"


def _literal_default(column) -> str | None:
    if column.server_default is not None:
        text_clause = getattr(column.server_default, "arg", None)
        return str(getattr(text_clause, "text", text_clause)) if text_clause else None

    default = column.default
    if default is None or default.is_callable or not default.is_scalar:
        return None

    value = default.arg
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        escaped = value.replace("'", "''")
        return f"'{escaped}'"
    return None

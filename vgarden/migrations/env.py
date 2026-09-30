"""Alembic environment, driven by Flask-Migrate.

Deliberately minimal: the engine and metadata come from the Flask app that
registered Flask-Migrate, and Python logging is left alone (the stock template
calls ``fileConfig()``, which silences the service's own loggers at startup).
"""

import logging

from alembic import context
from flask import current_app

config = context.config
logger = logging.getLogger("alembic.env")

migrate = current_app.extensions["migrate"]
target_metadata = migrate.db.metadata


def process_revision_directives(context, revision, directives):
    """Do not write an empty revision when ``flask db migrate`` finds no changes."""

    if getattr(config.cmd_opts, "autogenerate", False):
        if directives[0].upgrade_ops.is_empty():
            directives[:] = []
            logger.info("No changes in schema detected.")


conf_args = dict(migrate.configure_args)
conf_args.setdefault("process_revision_directives", process_revision_directives)


def run_migrations_offline() -> None:
    """``flask db upgrade --sql``: emit the DDL instead of running it."""

    url = migrate.db.engine.url.render_as_string(hide_password=False)
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True, **conf_args)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    with migrate.db.engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, **conf_args)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

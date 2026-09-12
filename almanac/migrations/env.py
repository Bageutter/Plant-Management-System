from alembic import context
from extensions import db

with db.engine.connect() as connection:
    context.configure(connection=connection, target_metadata=db.metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()

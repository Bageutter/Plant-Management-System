"""Stored photo, score band, confidence reason, duration; confidence as a label.

Adds the columns the Assessment model gained after the baseline and retypes
``confidence`` from a float to a short string (low / medium / high).

Written to be safe on every database this service has ever produced:

* a true baseline database gets all four columns added and the retype;
* a database from the create_all() + startup-ALTER stop-gap (health/schema.py,
  now removed) already has the columns, so only the ones actually missing are
  added, and the retype is skipped when it has already happened.

Values already stored in ``confidence`` are carried over as text; 0003 clears
the ones that are not valid labels.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-30

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None

ADDED_COLUMNS = {
    'image_data': sa.LargeBinary,
    'score_band': lambda: sa.String(length=80),
    'confidence_reason': sa.Text,
    'duration_ms': sa.Integer,
}


def _current_columns():
    inspector = sa.inspect(op.get_bind())
    return {column['name']: column for column in inspector.get_columns('assessments')}


def upgrade():
    columns = _current_columns()
    missing = [name for name in ADDED_COLUMNS if name not in columns]
    retype = not isinstance(columns['confidence']['type'], sa.String)
    if not missing and not retype:
        return

    # batch mode rebuilds the table on SQLite (which cannot ALTER a column type);
    # on PostgreSQL it issues ordinary ALTER TABLE statements.
    with op.batch_alter_table('assessments', schema=None) as batch_op:
        for name in missing:
            batch_op.add_column(sa.Column(name, ADDED_COLUMNS[name](), nullable=True))
        if retype:
            batch_op.alter_column(
                'confidence',
                existing_type=sa.Float(),
                type_=sa.String(length=10),
                existing_nullable=True,
                postgresql_using='confidence::text',
            )


def downgrade():
    with op.batch_alter_table('assessments', schema=None) as batch_op:
        batch_op.alter_column(
            'confidence',
            existing_type=sa.String(length=10),
            type_=sa.Float(),
            existing_nullable=True,
            # Labels cannot become numbers; a downgrade discards them.
            postgresql_using='NULL',
        )
        for name in reversed(list(ADDED_COLUMNS)):
            batch_op.drop_column(name)

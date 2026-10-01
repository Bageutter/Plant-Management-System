"""Normalise legacy confidence values to low / medium / high or NULL.

Rows written before confidence became a graded label stored a float such as
0.7 in the column (carried over as the text '0.7' by 0002). Those values mean
nothing as labels, so they are cleared; valid labels are lower-cased. The model
layer used to ignore such values at read time; after this revision the data
itself is clean.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-30

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None

LEVELS = "('low', 'medium', 'high')"


def upgrade():
    op.execute(sa.text(
        "UPDATE assessments SET confidence = lower(confidence) "
        f"WHERE confidence IS NOT NULL AND lower(confidence) IN {LEVELS}"
    ))
    op.execute(sa.text(
        "UPDATE assessments SET confidence = NULL "
        f"WHERE confidence IS NOT NULL AND lower(confidence) NOT IN {LEVELS}"
    ))


def downgrade():
    # Data cleanup: the discarded values were meaningless and cannot be restored.
    pass

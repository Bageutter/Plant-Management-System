"""Plant titles: a table of the plant names the gardener has used.

The assessment form offers previous plant names from a list, with an
"Other / new plant" option that adds a new title. Every distinct plant_ref
already recorded is copied in, so the list is complete on first start.
Assessments keep their own plant_ref text; deleting a title never touches them.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-30

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('plants',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name', name='uq_plants_name')
    )
    # Backfill from the names already used on assessments.
    op.execute(sa.text(
        "INSERT INTO plants (name, created_at) "
        "SELECT DISTINCT plant_ref, CURRENT_TIMESTAMP FROM assessments "
        "WHERE plant_ref IS NOT NULL AND trim(plant_ref) <> ''"
    ))


def downgrade():
    op.drop_table('plants')

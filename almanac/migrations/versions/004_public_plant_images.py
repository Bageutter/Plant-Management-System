"""Add public image URLs for imported catalogue photos."""

from alembic import op
import sqlalchemy as sa


revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("plant_images", sa.Column("public_url", sa.Text(), nullable=True))


def downgrade():
    raise RuntimeError("Restore a backup to undo this data-bearing migration.")

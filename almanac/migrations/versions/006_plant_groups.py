"""Store optional plant groups and variety names without changing record IDs."""

from alembic import op
import sqlalchemy as sa

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("plant_references") as batch:
        batch.add_column(sa.Column("plant_group", sa.String(120), nullable=True))
        batch.add_column(sa.Column("variety_name", sa.String(120), nullable=True))
        batch.add_column(sa.Column("plant_category", sa.String(40), nullable=True))


def downgrade():
    with op.batch_alter_table("plant_references") as batch:
        batch.drop_column("plant_category")
        batch.drop_column("variety_name")
        batch.drop_column("plant_group")

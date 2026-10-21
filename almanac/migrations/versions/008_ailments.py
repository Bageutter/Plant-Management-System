"""Add public ailment guides without changing legacy plant associations."""
from alembic import op
import sqlalchemy as sa
revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("ailments", sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("name", sa.String(160), nullable=False), sa.Column("category", sa.String(32), nullable=False),
        sa.Column("description", sa.Text()), sa.Column("payload", sa.JSON(), nullable=False))

def downgrade():
    op.drop_table("ailments")

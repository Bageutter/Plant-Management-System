"""Keep source and tool evidence with each chat answer."""
from alembic import op
import sqlalchemy as sa
revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None

def upgrade():
    with op.batch_alter_table("ai_chat_messages") as batch:
        batch.add_column(sa.Column("evidence", sa.JSON(), nullable=True))

def downgrade():
    with op.batch_alter_table("ai_chat_messages") as batch:
        batch.drop_column("evidence")

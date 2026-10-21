"""Health workflows: the link between this service and a Multi-Agent Server workflow (Release 2).

One row per workflow started from the records page or the API, holding the shared
server's workflow id, the plant the task was about, the task text and the last
status seen. The workflow's plan, answer, review and history live on the server.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-21

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('health_workflows',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('workflow_id', sa.String(length=64), nullable=False),
    sa.Column('plant_ref', sa.String(length=200), nullable=True),
    sa.Column('task', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=40), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('workflow_id', name='uq_health_workflows_workflow_id')
    )


def downgrade():
    op.drop_table('health_workflows')

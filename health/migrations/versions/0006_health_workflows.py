"""Multi-Agent workflows started from an assessment (Release 2).

One row per workflow, deleted with its assessment: the Multi-Agent Server's
workflow id, the task and the last seen status. Everything else stays on the
server.

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
    sa.Column('assessment_id', sa.Integer(), nullable=False),
    sa.Column('workflow_id', sa.String(length=64), nullable=False),
    sa.Column('task', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['assessment_id'], ['assessments.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('workflow_id')
    )
    with op.batch_alter_table('health_workflows', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_health_workflows_assessment_id'), ['assessment_id'], unique=False)


def downgrade():
    with op.batch_alter_table('health_workflows', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_health_workflows_assessment_id'))
    op.drop_table('health_workflows')

"""garden workflows (Release 2 multi-agent)

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-21 05:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('garden_workflows',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('garden_id', sa.Integer(), nullable=False),
    sa.Column('workflow_id', sa.String(length=64), nullable=False),
    sa.Column('task', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=40), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['garden_id'], ['gardens.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('workflow_id')
    )
    with op.batch_alter_table('garden_workflows', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_garden_workflows_garden_id'), ['garden_id'], unique=False)


def downgrade():
    with op.batch_alter_table('garden_workflows', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_garden_workflows_garden_id'))

    op.drop_table('garden_workflows')

"""Baseline: the assessments table as db.create_all() first built it.

This is the schema of the health service *before* the image_data, score_band,
confidence_reason and duration_ms columns were added and before confidence
became a graded low/medium/high label (it was a float). A database from that
era, or from the later create_all() + startup ALTER stop-gap, is adopted by
stamping this revision; 0002 then reconciles whatever it is missing.

Revision ID: 0001
Revises:
Create Date: 2026-09-30

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('assessments',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('plant_ref', sa.String(length=200), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('has_image', sa.Boolean(), nullable=False),
    sa.Column('image_mime', sa.String(length=64), nullable=True),
    sa.Column('model', sa.String(length=120), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('health_score', sa.Integer(), nullable=True),
    sa.Column('confidence', sa.Float(), nullable=True),
    sa.Column('plant_identification', sa.String(length=200), nullable=True),
    sa.Column('summary', sa.Text(), nullable=False),
    sa.Column('issues_json', sa.Text(), nullable=False),
    sa.Column('recommendations_json', sa.Text(), nullable=False),
    sa.Column('missing_information_json', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('assessments', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_assessments_plant_ref'), ['plant_ref'], unique=False)


def downgrade():
    with op.batch_alter_table('assessments', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_assessments_plant_ref'))

    op.drop_table('assessments')

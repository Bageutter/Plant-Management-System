"""Retain public catalogue provenance and additional botanical part labels."""
from alembic import op
import sqlalchemy as sa
revision = '009'
down_revision = '008'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('plant_references') as batch:
        batch.add_column(sa.Column('catalogue_provenance', sa.JSON(), nullable=True))
        batch.drop_constraint('part_used', type_='check')
        batch.create_check_constraint('part_used', "part_used IN ('leaf','leaves','root','fruit','flower','bark','seed','culm','swollen fruit stalk','flower (ornamental only)')")


def downgrade():
    raise RuntimeError('Restore a backup to remove data-bearing public catalogue provenance.')

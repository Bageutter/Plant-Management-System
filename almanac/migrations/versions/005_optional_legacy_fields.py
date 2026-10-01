"""Allow current plant inserts while retaining unused fields from older databases."""

from alembic import op
import sqlalchemy as sa


revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade():
    legacy_fields = {
        "plant_references": ("category", "difficulty", "icon"),
        "planting_months": ("climate_zone",),
        "plant_images": ("original_name", "content_type", "created_at"),
    }
    for table, names in legacy_fields.items():
        columns = {
            column["name"]: column
            for column in sa.inspect(op.get_bind()).get_columns(table)
        }
        required = [
            name for name in names if name in columns and not columns[name]["nullable"]
        ]
        if required:
            with op.batch_alter_table(table) as batch:
                for name in required:
                    batch.alter_column(name, existing_type=columns[name]["type"], nullable=True)


def downgrade():
    raise RuntimeError("Restore a backup to undo this compatibility migration.")

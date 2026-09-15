"""Track estimated fields and preserve/map optional legacy rotation wording."""

from alembic import op
import sqlalchemy as sa

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("plant_references", sa.Column("estimated_fields", sa.JSON(), nullable=True))
    groups = [
        ("Alliums", "medium", False),
        ("Brassicas", "heavy", False),
        ("Cucurbits", "heavy", False),
        ("Legumes", "light", False),
        ("Roots", "light", False),
        ("Solanums", "heavy", False),
        ("Anywhere", "light", True),
        ("Perennials", "medium", True),
    ]
    connection = op.get_bind()
    for name, weight, exempt in groups:
        connection.execute(
            sa.text(
                "INSERT INTO rotation_groups (name, feeder_weight, is_rotation_exempt) SELECT :n, :w, :e WHERE NOT EXISTS (SELECT 1 FROM rotation_groups WHERE name=:n)"
            ),
            {"n": name, "w": weight, "e": exempt},
        )
    columns = {c["name"] for c in sa.inspect(connection).get_columns("plant_references")}
    # Current main has no legacy rotation field. Support installations that do,
    # retaining unmatched wording for manual review rather than dropping it.
    if "rotation_group" in columns:
        aliases = {
            "allium": "Alliums",
            "brassica": "Brassicas",
            "cucurbit": "Cucurbits",
            "legume": "Legumes",
            "root": "Roots",
            "solanum": "Solanums",
            "solanaceae": "Solanums",
            "perennial": "Perennials",
        }
        aliases.update({name.lower(): name for name, _, _ in groups})
        for old, new in aliases.items():
            connection.execute(
                sa.text(
                    "UPDATE plant_references SET rotation_group_id=(SELECT id FROM rotation_groups WHERE name=:new) WHERE rotation_group_id IS NULL AND lower(trim(rotation_group))=:old"
                ),
                {"new": new, "old": old},
            )


def downgrade():
    raise RuntimeError("Restore a backup to undo this data-bearing migration.")

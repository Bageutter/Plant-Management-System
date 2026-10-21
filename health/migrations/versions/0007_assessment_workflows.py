"""Link optional assessment workflows without replacing existing workflow rows.

Revision ID: 0007
Revises: 0006
"""

from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

CONVENTION = {"uq": "uq_%(table_name)s_%(column_0_name)s",
              "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}
FK_NAME = "fk_health_workflows_assessment_id_assessments"
INDEX_NAME = "ix_health_workflows_assessment_id"


def upgrade():
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    columns = {column["name"]: column for column in inspector.get_columns("health_workflows")}
    # main's 0006 stores plant_ref. The unmerged assessment prototype used the
    # same revision number for assessment_id instead; accept that local layout too.
    with op.batch_alter_table("health_workflows", naming_convention=CONVENTION) as batch:
        if "plant_ref" not in columns:
            batch.add_column(sa.Column("plant_ref", sa.String(200), nullable=True))
        if "assessment_id" not in columns:
            batch.add_column(sa.Column("assessment_id", sa.Integer(), nullable=True))
            batch.create_foreign_key(FK_NAME, "assessments", ["assessment_id"], ["id"], ondelete="CASCADE")
            batch.create_index(INDEX_NAME, ["assessment_id"], unique=False)
        elif not columns["assessment_id"]["nullable"]:
            batch.alter_column("assessment_id", existing_type=sa.Integer(), nullable=True)
        if columns["status"]["type"].length != 40:
            batch.alter_column("status", existing_type=columns["status"]["type"], type_=sa.String(40))
    if "plant_ref" not in columns:
        connection.execute(sa.text(
            "UPDATE health_workflows SET plant_ref = "
            "(SELECT plant_ref FROM assessments WHERE assessments.id = health_workflows.assessment_id)"
        ))


def downgrade():
    with op.batch_alter_table("health_workflows", naming_convention=CONVENTION) as batch:
        batch.drop_index(INDEX_NAME)
        batch.drop_constraint(FK_NAME, type_="foreignkey")
        batch.drop_column("assessment_id")

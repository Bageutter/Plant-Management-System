from calendar import month_name
from datetime import datetime, timezone

from extensions import db


class PlantReference(db.Model):
    __tablename__ = "plant_references"

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(100), unique=True, nullable=False, index=True)
    common_name = db.Column(db.String(120), nullable=False, index=True)
    scientific_name = db.Column(db.String(160), nullable=False)
    family = db.Column(db.String(120), nullable=False)
    summary = db.Column(db.Text, nullable=False)
    created_at = db.Column(
        db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    planting_months = db.relationship(
        "PlantingMonth",
        back_populates="plant",
        cascade="all, delete-orphan",
        order_by="PlantingMonth.month_number",
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "slug": self.slug,
            "common_name": self.common_name,
            "scientific_name": self.scientific_name,
            "family": self.family,
            "summary": self.summary,
            "planting_months": [month.name for month in self.planting_months],
        }


class PlantingMonth(db.Model):
    __tablename__ = "planting_months"
    __table_args__ = (
        db.CheckConstraint(
            "month_number BETWEEN 1 AND 12",
            name="ck_planting_months_month_number",
        ),
        db.UniqueConstraint("plant_reference_id", "month_number"),
    )

    id = db.Column(db.Integer, primary_key=True)
    plant_reference_id = db.Column(
        db.Integer,
        db.ForeignKey("plant_references.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    month_number = db.Column(db.Integer, nullable=False)

    plant = db.relationship("PlantReference", back_populates="planting_months")

    @property
    def name(self) -> str:
        return month_name[self.month_number]


class AIChatMessage(db.Model):
    """One saved message in an authenticated user's Almanac conversation."""

    __tablename__ = "ai_chat_messages"
    __table_args__ = (
        db.CheckConstraint(
            "role IN ('user', 'assistant')", name="ck_ai_chat_message_role"
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    # Keep the existing database column name so local chat data needs no migration.
    owner_key = db.Column("session_id", db.String(64), nullable=False, index=True)
    role = db.Column(db.String(16), nullable=False)
    content = db.Column(db.Text, nullable=False)
    source_slugs = db.Column(db.JSON, nullable=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

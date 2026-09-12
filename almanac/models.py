from calendar import month_name
from datetime import datetime, timezone

from extensions import db
from catalogue import CHOICES, NUMERIC, TEXT


class PlantReference(db.Model):
    __tablename__ = "plant_references"

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(100), unique=True, nullable=False, index=True)
    common_name = db.Column(db.String(120), nullable=False, index=True)
    scientific_name = db.Column(db.String(160), nullable=False)
    family = db.Column(db.String(120), nullable=False)
    summary = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    yield_qty = db.Column(db.Float, nullable=True)
    in_row_spacing_cm = db.Column(db.Float, nullable=True)
    row_spacing_cm = db.Column(db.Float, nullable=True)
    succession_interval_days = db.Column(db.Integer, nullable=True)
    harvest_window_weeks = db.Column(db.Float, nullable=True)
    soil_ph_min = db.Column(db.Float, nullable=True)
    soil_ph_max = db.Column(db.Float, nullable=True)
    yield_wording = db.Column(db.Text, nullable=True)
    yield_unit = db.Column(db.Text, nullable=True)
    management_notes = db.Column(db.Text, nullable=True)
    care_notes = db.Column(db.Text, nullable=True)
    uses_notes = db.Column(db.Text, nullable=True)
    sowing_notes = db.Column(db.Text, nullable=True)
    source_url = db.Column(db.Text, nullable=True)
    notion_url = db.Column(db.Text, nullable=True)
    feeder_type = db.Column(
        db.Enum(
            *["heavy feeder", "light feeder", "nitrogen fixer"],
            name="feeder_type",
            native_enum=False,
            create_constraint=True,
        ),
        nullable=True,
    )
    water_needs = db.Column(
        db.Enum(
            *["low", "moderate", "high"],
            name="water_needs",
            native_enum=False,
            create_constraint=True,
        ),
        nullable=True,
    )
    sun_needs = db.Column(
        db.Enum(
            *["full sun", "part shade", "shade"],
            name="sun_needs",
            native_enum=False,
            create_constraint=True,
        ),
        nullable=True,
    )
    forest_layer = db.Column(
        db.Enum(
            *["canopy", "sub-canopy", "shrub", "herbaceous", "rhizosphere", "groundcover", "vine"],
            name="forest_layer",
            native_enum=False,
            create_constraint=True,
        ),
        nullable=True,
    )
    part_used = db.Column(
        db.Enum(
            *["leaf", "root", "fruit", "flower", "bark", "seed"],
            name="part_used",
            native_enum=False,
            create_constraint=True,
        ),
        nullable=True,
    )
    estimated_fields = db.Column(db.JSON, nullable=True)
    rotation_group_id = db.Column(db.Integer, db.ForeignKey("rotation_groups.id"), nullable=True)
    rotation_group = db.relationship("RotationGroup")
    pests = db.relationship("Pest", secondary="plant_pests")
    diseases = db.relationship("Disease", secondary="plant_diseases")
    function_tags = db.relationship("PlantFunctionTag", secondary="plant_function_tags")
    uses = db.relationship("PlantUse", secondary="plant_uses")
    guild_links = db.relationship(
        "PlantCompanion", foreign_keys="PlantCompanion.plant_id", cascade="all, delete-orphan"
    )
    __table_args__ = (
        db.CheckConstraint("yield_qty > 0", name="ck_yield_qty_positive"),
        db.CheckConstraint("in_row_spacing_cm > 0", name="ck_in_row_spacing_cm_positive"),
        db.CheckConstraint("row_spacing_cm > 0", name="ck_row_spacing_cm_positive"),
        db.CheckConstraint(
            "succession_interval_days > 0", name="ck_succession_interval_days_positive"
        ),
        db.CheckConstraint("harvest_window_weeks > 0", name="ck_harvest_window_weeks_positive"),
        db.CheckConstraint("soil_ph_min BETWEEN 0 AND 14", name="ck_ph_min"),
        db.CheckConstraint("soil_ph_max BETWEEN 0 AND 14", name="ck_ph_max"),
        db.CheckConstraint("soil_ph_min <= soil_ph_max", name="ck_ph_order"),
        db.CheckConstraint(
            "(yield_qty IS NULL AND yield_unit IS NULL) OR (yield_qty IS NOT NULL AND yield_unit IS NOT NULL)",
            name="ck_yield_pair",
        ),
    )

    planting_months = db.relationship(
        "PlantingMonth",
        back_populates="plant",
        cascade="all, delete-orphan",
        order_by="PlantingMonth.month_number",
    )
    image = db.relationship(
        "PlantImage",
        back_populates="plant",
        cascade="all, delete-orphan",
        uselist=False,
    )

    def to_dict(self) -> dict:
        return {
            **{
                key: getattr(self, key)
                for key in [*NUMERIC, *TEXT, *CHOICES, "source_url", "notion_url"]
            },
            "estimated_fields": self.estimated_fields or [],
            "rotation_group": self.rotation_group.to_dict() if self.rotation_group else None,
            **{
                key: [item.name for item in getattr(self, key)]
                for key in ["pests", "diseases", "function_tags", "uses"]
            },
            "guild_links": [
                {
                    "slug": link.companion.slug,
                    "name": link.companion.common_name,
                    "function": link.function.name,
                    "notes": link.notes,
                }
                for link in self.guild_links
            ],
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


class PlantImage(db.Model):
    __tablename__ = "plant_images"

    id = db.Column(db.Integer, primary_key=True)
    plant_reference_id = db.Column(
        db.Integer,
        db.ForeignKey("plant_references.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    filename = db.Column(db.String(80), nullable=False, unique=True)

    plant = db.relationship("PlantReference", back_populates="image")


class AIChatMessage(db.Model):
    """One saved message in an authenticated user's Almanac conversation."""

    __tablename__ = "ai_chat_messages"
    __table_args__ = (
        db.CheckConstraint("role IN ('user', 'assistant')", name="ck_ai_chat_message_role"),
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


class AILoopRun(db.Model):
    """Evidence of one Plan -> Act -> Observe -> Adapt run behind an assistant answer.

    New table (no ALTER on ai_chat_messages) so db.create_all() is enough.
    """

    __tablename__ = "ai_loop_runs"

    id = db.Column(db.Integer, primary_key=True)
    owner_key = db.Column(db.String(64), nullable=False, index=True)
    message_id = db.Column(
        db.Integer, db.ForeignKey("ai_chat_messages.id"), nullable=True, index=True
    )
    run_id = db.Column(db.String(64), nullable=False, unique=True)
    question = db.Column(db.Text, nullable=False)
    final_answer = db.Column(db.Text, nullable=False)
    iterations = db.Column(db.Integer, nullable=False)
    verdict = db.Column(db.String(24), nullable=False)  # approved | revised_capped | fallback
    transcript_path = db.Column(db.String(255), nullable=False)
    trace = db.Column(db.JSON, nullable=False)
    created_at = db.Column(
        db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    message = db.relationship("AIChatMessage", backref=db.backref("loop_run", uselist=False))


class RotationGroup(db.Model):
    __tablename__ = "rotation_groups"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(40), unique=True, nullable=False)
    feeder_weight = db.Column(
        db.Enum(
            "light",
            "medium",
            "heavy",
            name="feeder_weight",
            native_enum=False,
            create_constraint=True,
        ),
        nullable=False,
    )
    is_rotation_exempt = db.Column(db.Boolean, nullable=False, default=False)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "feeder_weight": self.feeder_weight,
            "is_rotation_exempt": self.is_rotation_exempt,
        }


class Pest(db.Model):
    __tablename__ = "pests"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.Text, nullable=True)


plant_pests = db.Table(
    "plant_pests",
    db.Column(
        "plant_id",
        db.Integer,
        db.ForeignKey("plant_references.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    db.Column(
        "tag_id", db.Integer, db.ForeignKey("pests.id", ondelete="CASCADE"), primary_key=True
    ),
)


class Disease(db.Model):
    __tablename__ = "diseases"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.Text, nullable=True)


plant_diseases = db.Table(
    "plant_diseases",
    db.Column(
        "plant_id",
        db.Integer,
        db.ForeignKey("plant_references.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    db.Column(
        "tag_id", db.Integer, db.ForeignKey("diseases.id", ondelete="CASCADE"), primary_key=True
    ),
)


class PlantFunctionTag(db.Model):
    __tablename__ = "function_tags"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.Text, nullable=True)


plant_function_tags = db.Table(
    "plant_function_tags",
    db.Column(
        "plant_id",
        db.Integer,
        db.ForeignKey("plant_references.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    db.Column(
        "tag_id",
        db.Integer,
        db.ForeignKey("function_tags.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class PlantUse(db.Model):
    __tablename__ = "uses"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.Text, nullable=True)


plant_uses = db.Table(
    "plant_uses",
    db.Column(
        "plant_id",
        db.Integer,
        db.ForeignKey("plant_references.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    db.Column("tag_id", db.Integer, db.ForeignKey("uses.id", ondelete="CASCADE"), primary_key=True),
)


class PlantCompanion(db.Model):
    __tablename__ = "plant_companions"
    plant_id = db.Column(
        db.Integer, db.ForeignKey("plant_references.id", ondelete="CASCADE"), primary_key=True
    )
    companion_id = db.Column(
        db.Integer, db.ForeignKey("plant_references.id", ondelete="CASCADE"), primary_key=True
    )
    function_id = db.Column(db.Integer, db.ForeignKey("function_tags.id"), primary_key=True)
    notes = db.Column(db.Text, nullable=True)
    companion = db.relationship("PlantReference", foreign_keys=[companion_id])
    function = db.relationship("PlantFunctionTag")
    __table_args__ = (db.CheckConstraint("plant_id != companion_id", name="ck_companion_not_self"),)

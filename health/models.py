import json
from datetime import datetime, timezone

from sqlalchemy import func

from ai import CONFIDENCE_LEVELS
from extensions import db


class Plant(db.Model):
    """A plant name the gardener has used, offered as a choice on the form.

    Titles are registered the first time a name is used on an assessment (or
    added on the plant names page). An assessment keeps its own ``plant_ref``
    text rather than a foreign key, so removing a title never alters or hides a
    record: it only stops the name being offered for new assessments.
    """

    __tablename__ = "plants"
    __table_args__ = (db.UniqueConstraint("name", name="uq_plants_name"),)

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    @classmethod
    def find(cls, name: str) -> "Plant | None":
        """Case-insensitive lookup by name."""

        return cls.query.filter(func.lower(cls.name) == name.strip().lower()).first()

    @classmethod
    def register(cls, name: str | None) -> "Plant | None":
        """Return the title for ``name``, creating it if new. The caller commits."""

        if not name or not name.strip():
            return None
        existing = cls.find(name)
        if existing is not None:
            return existing
        plant = cls(name=name.strip())
        db.session.add(plant)
        return plant

    @classmethod
    def ordered(cls) -> list["Plant"]:
        return cls.query.order_by(func.lower(cls.name)).all()

    @property
    def assessment_count(self) -> int:
        return Assessment.query.filter(func.lower(Assessment.plant_ref) == self.name.lower()).count()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "assessments": self.assessment_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Assessment(db.Model):
    """A single plant health assessment produced by the local AI model."""

    __tablename__ = "assessments"

    id = db.Column(db.Integer, primary_key=True)

    # Free-form reference to the plant supplied by the caller. The mapping between
    # this value and a Virtual Garden plant is not decided yet, so it is not a
    # foreign key and is never resolved against another service.
    plant_ref = db.Column(db.String(200), nullable=True, index=True)

    description = db.Column(db.Text, nullable=True)
    has_image = db.Column(db.Boolean, nullable=False, default=False)
    image_mime = db.Column(db.String(64), nullable=True)
    # The downscaled image actually sent for inference, retained so a past
    # assessment can be reviewed alongside the photo it was based on.
    image_data = db.Column(db.LargeBinary, nullable=True)

    model = db.Column(db.String(120), nullable=False)
    status = db.Column(db.String(20), nullable=False)
    health_score = db.Column(db.Integer, nullable=True)
    score_band = db.Column(db.String(80), nullable=True)
    confidence = db.Column(db.String(10), nullable=True)
    confidence_reason = db.Column(db.Text, nullable=True)
    duration_ms = db.Column(db.Integer, nullable=True)
    plant_identification = db.Column(db.String(200), nullable=True)
    summary = db.Column(db.Text, nullable=False, default="")
    issues_json = db.Column(db.Text, nullable=False, default="[]")
    recommendations_json = db.Column(db.Text, nullable=False, default="[]")
    missing_information_json = db.Column(db.Text, nullable=False, default="[]")

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    @property
    def history_entry(self) -> dict:
        """The compact form of this record given to the model as context."""

        return {
            "id": self.id,
            "created_at": self.created_at.strftime("%Y-%m-%d") if self.created_at else "",
            "status": self.status,
            "health_score": self.health_score,
            "summary": self.summary,
        }

    @property
    def issues(self) -> list[dict]:
        return json.loads(self.issues_json)

    @property
    def recommendations(self) -> list[dict]:
        return json.loads(self.recommendations_json)

    @property
    def missing_information(self) -> list[str]:
        return json.loads(self.missing_information_json)

    @property
    def confidence_level(self) -> str | None:
        """The confidence as a valid level, or None.

        Migration 0003 cleared the floats (e.g. 0.7) that records stored before
        confidence became a graded level; this stays defensive so an unexpected
        value is reported as "no confidence recorded" rather than rendered verbatim.
        """
        value = self.confidence
        if isinstance(value, str) and value.lower() in CONFIDENCE_LEVELS:
            return value.lower()
        return None

    @classmethod
    def from_result(
        cls,
        result: dict,
        *,
        model: str,
        plant_ref: str | None,
        description: str | None,
        has_image: bool,
        image_mime: str | None,
        image_data: bytes | None = None,
    ) -> "Assessment":
        return cls(
            plant_ref=plant_ref,
            description=description,
            has_image=has_image,
            image_mime=image_mime,
            image_data=image_data,
            model=model,
            status=result["status"],
            health_score=result["health_score"],
            score_band=result["score_band"],
            confidence=result["confidence"],
            confidence_reason=result["confidence_reason"],
            duration_ms=result.get("duration_ms"),
            plant_identification=result["plant_identification"],
            summary=result["summary"],
            issues_json=json.dumps(result["issues"]),
            recommendations_json=json.dumps(result["recommendations"]),
            missing_information_json=json.dumps(result["missing_information"]),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "plant_ref": self.plant_ref,
            "description": self.description,
            "has_image": self.has_image,
            "image_mime": self.image_mime,
            "model": self.model,
            "status": self.status,
            "health_score": self.health_score,
            "score_band": self.score_band,
            "confidence": self.confidence_level,
            "confidence_reason": self.confidence_reason,
            "duration_ms": self.duration_ms,
            "plant_identification": self.plant_identification,
            "summary": self.summary,
            "issues": self.issues,
            "recommendations": self.recommendations,
            "missing_information": self.missing_information,
            "created_at": self.created_at.isoformat(),
            "loop": self.loop_run.summary() if self.loop_run else None,
        }


class AssessmentLoopRun(db.Model):
    """Evidence of the Perceive → Reason → Act → Observe → Repeat run behind an assessment."""

    __tablename__ = "assessment_loop_runs"
    __table_args__ = (db.UniqueConstraint("run_id", name="uq_assessment_loop_runs_run_id"),)

    VERDICT_LABELS = {
        "approved": "approved by the reviewer",
        "revised_capped": "revised, iteration cap reached",
        "fallback": "checks only (no reviewer model)",
    }

    id = db.Column(db.Integer, primary_key=True)
    assessment_id = db.Column(
        db.Integer, db.ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    run_id = db.Column(db.String(64), nullable=False)
    reviewer_model = db.Column(db.String(120), nullable=True)
    iterations = db.Column(db.Integer, nullable=False)
    verdict = db.Column(db.String(24), nullable=False)  # approved | revised_capped | fallback
    transcript_path = db.Column(db.String(255), nullable=True)
    trace = db.Column(db.JSON, nullable=False)  # list of phase events
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    assessment = db.relationship(
        "Assessment",
        backref=db.backref("loop_run", uselist=False, cascade="all, delete-orphan"),
    )

    @classmethod
    def from_outcome(cls, outcome) -> "AssessmentLoopRun":
        return cls(
            run_id=outcome.run_id,
            reviewer_model=outcome.reviewer_model,
            iterations=outcome.iterations,
            verdict=outcome.verdict,
            transcript_path=outcome.transcript_path or None,
            trace=outcome.trace,
        )

    @property
    def reviewed(self) -> bool:
        return self.verdict != "fallback"

    @property
    def verdict_label(self) -> str:
        return self.VERDICT_LABELS.get(self.verdict, self.verdict)

    def summary(self) -> dict:
        return {
            "run_id": self.run_id,
            "iterations": self.iterations,
            "verdict": self.verdict,
            "reviewed": self.reviewed,
        }

    def to_dict(self) -> dict:
        from agentic import WORKFLOW

        return {
            **self.summary(),
            "workflow": WORKFLOW,
            "assessment_id": self.assessment_id,
            "reviewer_model": self.reviewer_model,
            "transcript_path": self.transcript_path,
            "trace": self.trace,
            "created_at": self.created_at.isoformat(),
        }

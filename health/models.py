import json
from datetime import datetime, timezone

from ai import CONFIDENCE_LEVELS
from extensions import db


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

    # Free-text follow-up notes the gardener can edit after the assessment
    # (e.g. "watered less, new leaves look better after a week").
    notes = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime, default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

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

        Records written before confidence became a graded level stored a float
        (e.g. 0.7) in this column. Those values are meaningless as labels, so they
        are reported as "no confidence recorded" rather than rendered verbatim.
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
            "notes": self.notes,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

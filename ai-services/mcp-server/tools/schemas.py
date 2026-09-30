"""Pinned result schemas for every registered tool.

Publishing these as ``outputSchema`` is part of the tool contract: a client can be
written against the shape before the behaviour behind a stub exists, and a tool can
never return a field the schema does not declare.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

# --------------------------------------------------------------------------- #
# Shared input constraints                                                    #
# --------------------------------------------------------------------------- #

PlantRef = Annotated[str, Field(min_length=1, max_length=200)]
Description = Annotated[str, Field(min_length=1, max_length=4000)]
RecordId = Annotated[int, Field(ge=1, strict=True)]
Limit = Annotated[int, Field(ge=1, le=50, strict=True)]
Query = Annotated[str, Field(max_length=120)]
Slug = Annotated[str, Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=100)]

HealthStatusValue = Literal["healthy", "at_risk", "unhealthy", "unknown"]
Confidence = Literal["low", "medium", "high"]


# --------------------------------------------------------------------------- #
# Plant Health                                                                #
# --------------------------------------------------------------------------- #


class HealthServiceStatus(BaseModel):
    service: str
    status: Literal["ok", "degraded"]
    ai_reachable: bool
    model: str | None = None
    url: str


class Issue(BaseModel):
    name: str
    severity: Literal["low", "medium", "high"]
    evidence: str = ""


class Recommendation(BaseModel):
    action: str
    priority: Literal["low", "medium", "high"]
    details: str = ""


class AssessmentSummary(BaseModel):
    id: int
    plant_ref: str | None
    plant_identification: str | None
    status: HealthStatusValue
    health_score: int | None
    score_band: str | None
    confidence: Confidence | None
    summary: str
    has_image: bool
    created_at: str
    url: str


class Assessment(AssessmentSummary):
    description: str | None
    confidence_reason: str | None
    model: str
    duration_ms: int | None
    issues: list[Issue]
    recommendations: list[Recommendation]
    missing_information: list[str]


class AssessmentList(BaseModel):
    items: list[AssessmentSummary]
    count: int
    plant_ref: str | None
    status: HealthStatusValue | None
    evidence_note: str


class ScorePoint(BaseModel):
    assessment_id: int
    created_at: str
    health_score: int | None
    status: HealthStatusValue


class RecurringIssue(BaseModel):
    name: str
    occurrences: int
    worst_severity: Literal["low", "medium", "high"]


class HealthHistorySummary(BaseModel):
    plant_ref: str
    assessments: int
    status_counts: dict[HealthStatusValue, int]
    latest: AssessmentSummary | None
    score_trend: list[ScorePoint]
    recurring_issues: list[RecurringIssue]
    evidence_note: str


# --------------------------------------------------------------------------- #
# Plant Almanac (stub contract — see the tracking issue in tools/almanac.py)  #
# --------------------------------------------------------------------------- #


class AlmanacReference(BaseModel):
    kind: Literal["plant", "pest", "disease"]
    id: int
    key: str
    name: str
    uri: str
    path: str


class AlmanacSearchPage(BaseModel):
    items: list[AlmanacReference]
    total: int
    limit: int
    offset: int
    next_offset: int | None


class AlmanacPlantDetail(AlmanacReference):
    record: dict[str, Any]
    pests: list[AlmanacReference]
    diseases: list[AlmanacReference]
    evidence_note: str


# --------------------------------------------------------------------------- #
# Virtual Garden (stub contract — see the tracking issue in tools/vgarden.py) #
# --------------------------------------------------------------------------- #


class Planting(BaseModel):
    id: int
    crop_name: str
    quantity: int | None
    lifecycle_state: str | None
    growth_stage: str | None
    planted_date: str | None
    expected_harvest_date: str | None
    location: str | None


class GardenSnapshot(BaseModel):
    garden_id: int
    name: str
    location_label: str | None
    climate_zone: str | None
    areas: list[dict[str, Any]]
    containers: list[dict[str, Any]]
    plantings: list[Planting]
    evidence_note: str


class PlantingList(BaseModel):
    garden_id: int
    items: list[Planting]
    count: int

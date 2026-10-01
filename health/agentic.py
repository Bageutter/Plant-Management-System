"""Agentic loop for a plant health assessment: Perceive → Reason → Act → Observe → Repeat.

A single vision-model call is *defended* (response schema, clamping in code) but
it never checks its own work. This module wraps that call in an explicit loop,
the health-service sibling of the chat loop in ``shared/ai_loop.py``:

  PERCEIVE  gather the evidence the model may use — what was supplied (photo,
            description, plant name) and this plant's earlier assessments — as
            a JSON grounding.
  REASON    the vision model drafts the structured assessment from that
            evidence (plus, from the second pass, the reviewer's guidance).
  ACT       turn the draft into the candidate report: normalise and clamp it,
            derive the score band, count what it proposes.
  OBSERVE   check the candidate: deterministic consistency checks in code, then
            an independent reviewer model that reads the candidate against the
            same grounding and answers approved / revise with concrete guidance.
  REPEAT    approved → done; revise → carry the guidance into the next REASON,
            up to ``max_iterations``; cap reached → return the last candidate,
            marked ``revised_capped``.

Every phase of every run is logged the same three ways as the chat loop (stdout,
JSONL, markdown transcript) through the shared ``LoopLogger``, stored on the
assessment as an ``AssessmentLoopRun`` row, and shown in the product.

The reviewer cannot see the photo. It checks what *can* be checked without it:
that the report only claims what the evidence supports (no photo described when
none was given), that status, score and confidence agree with each other, and
that the recommendations are concrete and follow from the issues.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

from ai import SCORE_BANDS, AIUnavailableError, OllamaClient

try:
    import ai_loop  # shared/ai_loop.py, mounted into the container / on sys.path locally
except ImportError:  # pragma: no cover - bare image without the shared module
    ai_loop = None

log = logging.getLogger("ai_loop")

WORKFLOW = "Perceive → Reason → Act → Observe → Repeat"
PHASES = ("perceive", "reason", "act", "observe", "repeat")

# What a status may score, per the bands in ai.SYSTEM_PROMPT / SCORE_BANDS.
STATUS_SCORE_RANGES = {
    "healthy": (60, 100),
    "at_risk": (30, 84),
    "unhealthy": (0, 29),
}

REVIEW_PROMPT = """You are an independent reviewer of a plant health ASSESSMENT written by a
vision model for a home gardener. You cannot see the photo. Review only what can be
checked without it.

GROUNDING says exactly what evidence the model was given: whether there was a photo,
the gardener's own description, the plant name, and earlier assessments of the same
plant. The assessment may state anything supported by that evidence, and when a
photo was given it may describe what a photo would plausibly show.

Return "revise" only when one of these is clearly true:
- The assessment describes or judges a photo although GROUNDING says no photo was
  given, or denies having a photo although one was given.
- confidence_reason contradicts the evidence line in GROUNDING.
- status, health_score and confidence contradict each other (a "healthy" plant
  scored as dying, a "high" confidence with an "unknown" status).
- A recommendation is not a concrete gardening action, or contradicts the issues.
- The summary asserts an observation that cannot come from the evidence given.

Otherwise return "approved". When genuinely unsure, return "approved".

Return JSON only, exactly these keys:
{
  "verdict": "approved" or "revise",
  "issues": ["short, specific problem", ...],   // empty list when approved
  "guidance": "one concrete instruction for the next draft"   // "" when approved
}"""


class LoopUnavailable(AIUnavailableError):
    """The loop could not produce any assessment (the vision model failed)."""


@dataclass
class LoopOutcome:
    result: dict
    iterations: int
    verdict: str  # "approved" | "revised_capped" | "fallback"
    run_id: str
    transcript_path: str
    reviewer_model: str | None
    trace: list[dict] = field(default_factory=list)

    @property
    def reviewed(self) -> bool:
        """Whether an independent model (not only the code checks) observed the draft."""

        return self.verdict != "fallback"


# --------------------------------------------------------------------------- #
# Logging fallback for a bare image (no shared/ai_loop.py mounted)             #
# --------------------------------------------------------------------------- #


class _StdoutLogger:
    """Same ``phase()`` contract as ai_loop.LoopLogger, stdout only."""

    def __init__(self, service: str, run_id: str):
        self.service = service
        self.run_id = run_id
        self.started = time.monotonic()
        self.events: list[dict] = []
        self.transcript_path = ""

    def phase(self, name: str, data: dict, *, body: str | None = None) -> None:
        if body is not None:
            data = {**data, "answer": body}
        event = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "run_id": self.run_id,
            "service": self.service,
            "phase": name,
            "elapsed_ms": int((time.monotonic() - self.started) * 1000),
            **data,
        }
        self.events.append(event)
        log.info("[%s] %s %s", self.run_id, name.upper(), " ".join(f"{k}={v}" for k, v in data.items()))


def _make_logger(service: str, log_dir: str, run_id: str, question: str):
    if ai_loop is None:
        return _StdoutLogger(service, run_id)
    os.makedirs(log_dir, exist_ok=True)
    return ai_loop.LoopLogger(service, log_dir, run_id, question, workflow=WORKFLOW)


# --------------------------------------------------------------------------- #
# PERCEIVE                                                                    #
# --------------------------------------------------------------------------- #


def perceive(
    description: str | None,
    image_b64: str | None,
    plant_ref: str | None,
    history: list[dict] | None,
) -> dict:
    """The grounding: exactly what the model was given, and nothing else."""

    has_image = bool(image_b64)
    if has_image and description:
        evidence = "one photo and a written description"
    elif has_image:
        evidence = "one photo, and no written description"
    else:
        evidence = "a written description only, and no photo"
    return {
        "evidence": evidence,
        "has_image": has_image,
        "plant_ref": plant_ref,
        "description": description,
        "earlier_assessments": list(history or [])[:3],
    }


# --------------------------------------------------------------------------- #
# OBSERVE: deterministic checks                                               #
# --------------------------------------------------------------------------- #

_SEES_PHOTO = re.compile(r"\b(in|from|on) (the|this|your) (photo|image|picture)\b", re.I)
_DENIES_PHOTO = re.compile(r"\b(no|without a|not given a|was not provided a) (photo|image|picture)\b", re.I)


def observe_checks(candidate: dict, grounding: dict) -> list[str]:
    """Consistency problems a program can find without any model."""

    problems: list[str] = []
    status = candidate.get("status")
    score = candidate.get("health_score")

    if status in STATUS_SCORE_RANGES and score is not None:
        low, high = STATUS_SCORE_RANGES[status]
        if not low <= score <= high:
            problems.append(
                f"health_score {score} is outside the {low}-{high} band for status '{status}'"
            )

    texts = " ".join(
        str(part)
        for part in (
            candidate.get("summary"),
            candidate.get("confidence_reason"),
            *(issue.get("evidence") for issue in candidate.get("issues") or []),
        )
        if part
    )
    if not grounding.get("has_image") and _SEES_PHOTO.search(texts):
        problems.append("the assessment describes a photo, but no photo was provided")
    if grounding.get("has_image") and _DENIES_PHOTO.search(candidate.get("confidence_reason") or ""):
        problems.append("confidence_reason denies the photo that was provided")

    if status in ("at_risk", "unhealthy") and not candidate.get("recommendations"):
        problems.append(f"status '{status}' but no recommendation was given")
    if status == "healthy" and any(
        issue.get("severity") == "high" for issue in candidate.get("issues") or []
    ):
        problems.append("status 'healthy' contradicts a high-severity issue")
    return problems


# --------------------------------------------------------------------------- #
# The loop                                                                    #
# --------------------------------------------------------------------------- #

Progress = Callable[[dict], None]


class HealthAssessmentLoop:
    def __init__(
        self,
        client,
        reviewer,
        log_dir: str,
        max_iterations: int = 2,
        service: str = "health",
    ):
        # ``client`` and ``reviewer`` may be the objects themselves or zero-argument
        # callables returning them, so the loop always uses whatever the app
        # currently holds in ``app.extensions`` (tests swap in fakes after start-up).
        self._client = client
        self._reviewer = reviewer
        self.log_dir = log_dir
        self.max_iterations = max(1, max_iterations)
        self.service = service

    @property
    def client(self) -> OllamaClient:
        return self._client() if callable(self._client) else self._client

    @property
    def reviewer(self):
        return self._reviewer() if callable(self._reviewer) else self._reviewer

    @property
    def reviewer_model(self) -> str | None:
        reviewer = self.reviewer
        return getattr(reviewer, "model", None) if reviewer is not None else None

    def run(
        self,
        description: str | None,
        image_b64: str | None,
        plant_ref: str | None,
        *,
        history: list[dict] | None = None,
        progress: Progress | None = None,
    ) -> LoopOutcome:
        """Run the loop. Raises ``LoopUnavailable`` if the model never answered."""

        run_id = "{}-{}-{}".format(
            self.service, datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S"), uuid.uuid4().hex[:6]
        )
        question = f"Assess the health of {plant_ref or 'the plant'}"
        logger = _make_logger(self.service, self.log_dir, run_id, question)
        emit = progress or (lambda event: None)

        # -- PERCEIVE ----------------------------------------------------------
        grounding = perceive(description, image_b64, plant_ref, history)
        logger.phase(
            "perceive",
            {
                "question": question,
                "evidence": grounding["evidence"],
                "plant_ref": plant_ref or "(none)",
                "description_chars": len(description or ""),
                "earlier_assessments": len(grounding["earlier_assessments"]),
            },
        )
        emit({"type": "phase", "phase": "perceive", "iteration": 0, "detail": grounding["evidence"]})

        feedback: str | None = None
        candidate: dict | None = None
        verdict = "fallback"
        for i in range(1, self.max_iterations + 1):
            # -- REASON --------------------------------------------------------
            t0 = time.monotonic()
            emit({"type": "phase", "phase": "reason", "iteration": i, "detail": "Drafting the assessment"})
            draft = self._reason(description, image_b64, plant_ref, grounding, feedback, i, progress)
            logger.phase(
                "reason",
                {
                    "iteration": i,
                    "carried_feedback": feedback or "(none)",
                    "draft": json.dumps(draft, ensure_ascii=False),
                    "ms": int((time.monotonic() - t0) * 1000),
                },
            )

            # -- ACT -----------------------------------------------------------
            candidate = draft  # already normalised and clamped by ai.parse_content
            logger.phase(
                "act",
                {
                    "iteration": i,
                    "status": candidate["status"],
                    "health_score": candidate["health_score"],
                    "score_band": candidate["score_band"],
                    "confidence": candidate["confidence"],
                    "issues": len(candidate["issues"]),
                    "recommendations": len(candidate["recommendations"]),
                },
            )

            # -- OBSERVE -------------------------------------------------------
            t0 = time.monotonic()
            emit({"type": "phase", "phase": "observe", "iteration": i, "detail": "Checking the draft"})
            problems = observe_checks(candidate, grounding)
            review = self._review(question, grounding, candidate, logger, i)
            reviewed = review is not None
            issues = problems + (review["issues"] if reviewed else [])
            approved = not problems and (not reviewed or review["verdict"] == "approved")
            logger.phase(
                "observe",
                {
                    "iteration": i,
                    "checks": "; ".join(problems) or "(none)",
                    "reviewer": self.reviewer_model if reviewed else "(checks only)",
                    "verdict": "approved" if approved else "revise",
                    "issues": "; ".join(issues) or "(none)",
                    "ms": int((time.monotonic() - t0) * 1000),
                },
            )

            # -- REPEAT --------------------------------------------------------
            if approved:
                verdict = "approved" if reviewed else "fallback"
                logger.phase("repeat", {"iteration": i, "decision": "accept"})
                break

            guidance = (review or {}).get("guidance") or ""
            feedback = "; ".join(part for part in (guidance, *problems) if part) or "Revise the assessment."
            if i < self.max_iterations:
                logger.phase("repeat", {"iteration": i, "decision": "revise", "guidance": feedback})
                emit({"type": "phase", "phase": "repeat", "iteration": i, "detail": feedback})
            else:
                verdict = "revised_capped" if reviewed else "fallback"
                logger.phase("repeat", {"iteration": i, "decision": "stop_capped", "guidance": feedback})

        assert candidate is not None
        return LoopOutcome(
            result=candidate,
            iterations=i,
            verdict=verdict,
            run_id=run_id,
            transcript_path=logger.transcript_path,
            reviewer_model=self.reviewer_model,
            trace=logger.events,
        )

    # -- helpers ------------------------------------------------------------------

    def _reason(self, description, image_b64, plant_ref, grounding, feedback, iteration, progress) -> dict:
        """One vision-model draft, streamed when a progress sink is listening."""

        kwargs = dict(
            description=description,
            image_b64=image_b64,
            plant_ref=plant_ref,
            feedback=feedback,
            history=grounding["earlier_assessments"],
        )
        client = self.client
        if progress is None:
            return client.assess(**kwargs)

        for event in client.assess_stream(**kwargs):
            if event["type"] == "result":
                return event["result"]
            if event["type"] == "error":
                raise LoopUnavailable(event["message"])
            progress({**event, "phase": "reason", "iteration": iteration, "iterations_max": self.max_iterations})
        raise LoopUnavailable("The local AI model ended the stream without an answer.")

    def _review(self, question, grounding, candidate, logger, iteration) -> dict | None:
        """The reviewer model's verdict, or None when reviewing is unavailable."""

        reviewer = self.reviewer
        if reviewer is None:
            return None
        try:
            return reviewer.review(
                question, grounding, json.dumps(candidate, ensure_ascii=False, indent=2)
            )
        except Exception as exc:  # noqa: BLE001 - a reviewer outage must never break an assessment
            logger.phase("fallback", {"iteration": iteration, "reason": f"reviewer unavailable: {exc}"})
            return None


def build_reviewer(config) -> "ai_loop.Reviewer | None":
    """A health-prompted reviewer from app config, or None (checks-only loop)."""

    model = config.get("OLLAMA_REVIEW_MODEL")
    if not model or ai_loop is None:
        return None
    return ai_loop.Reviewer(
        base_url=config.get("OLLAMA_URL", "http://localhost:11434"),
        model=model,
        timeout=config.get("OLLAMA_TIMEOUT", 180),
        auto_pull=config.get("OLLAMA_AUTO_PULL", False),
        prompt=REVIEW_PROMPT,
    )


def band_for(score: int | None) -> str | None:
    for low, high, label in SCORE_BANDS:
        if score is not None and low <= score <= high:
            return label
    return None

"""Client for the locally hosted AI (Ollama) used to assess plant health.

The service deliberately keeps all inference local: images and descriptions are
sent to an Ollama instance on the local network and never to a third party.
"""

from __future__ import annotations

import json
import logging
import re
import time

import requests

logger = logging.getLogger(__name__)

STATUSES = ("healthy", "at_risk", "unhealthy", "unknown")
SEVERITIES = ("low", "medium", "high")
PRIORITIES = ("low", "medium", "high")
CONFIDENCE_LEVELS = ("low", "medium", "high")
MAX_LIST_ITEMS = 4

SYSTEM_PROMPT = (
    "You are a horticultural plant health analyst for a small home garden system. "
    "You are given a photo of a plant, a written description of it, or both. "
    "Assess whether the plant is healthy and, when it is not, explain what should be "
    "done to improve its health.\n"
    "Rules:\n"
    "- Base your assessment only on the evidence provided. Do not invent observations.\n"
    "- If the evidence is too thin to judge, use status \"unknown\" and list what extra "
    "information or photos would help.\n"
    "- Recommendations must be concrete, actionable gardening steps a home gardener can "
    "carry out (e.g. \"reduce watering to twice a week until the top 3cm of soil dries\").\n"
    "- Prefer the least invasive effective action first.\n"
    "- Be concise. Report at most 4 issues and at most 4 recommendations, most important "
    "first. Keep every text field under 200 characters.\n"
    "- Respond only with JSON matching the requested schema.\n"
    "\n"
    "health_score is a 0-100 rating of the plant's overall condition, where 100 is a "
    "thriving plant and 0 is a dead one. Use these bands, and keep the score consistent "
    "with the status you report:\n"
    "- 85-100 (healthy): thriving, no action needed beyond routine care.\n"
    "- 60-84 (healthy or at_risk): minor cosmetic issues, easily corrected.\n"
    "- 30-59 (at_risk): clear problems that will worsen without intervention.\n"
    "- 0-29 (unhealthy): severe decline, dying, or already dead.\n"
    "If the status is \"unknown\", set health_score to 0; it is not shown to the user.\n"
    "\n"
    "confidence is how sure you are of this assessment, given only the evidence you were "
    "actually given. Judge it honestly — most home-garden reports deserve \"medium\" at "
    "best, and you should not claim \"high\" merely because you produced an answer:\n"
    "- high: clear, unambiguous evidence (e.g. a sharp photo showing a distinctive, "
    "well-known symptom, or a detailed description covering watering, light and soil).\n"
    "- medium: the evidence points one way but an important detail is missing or the "
    "symptom has several plausible causes.\n"
    "- low: the evidence is vague, blurry, contradictory, or could fit many conditions. "
    "Use this whenever you are mostly guessing.\n"
    "confidence_reason must state, in one short sentence, what specifically limits or "
    "supports your confidence. It must be consistent with the EVIDENCE PROVIDED line in "
    "the user message. If you were given a photo, do not claim you were not given one. If "
    "you were not given a photo, never describe or judge one — you may only say that a "
    "photo would help. The same applies to the written description. Quote or paraphrase "
    "the gardener's own details where you can, and do not use generic filler."
)

# Bands used to explain the score in the UI. Kept in sync with SYSTEM_PROMPT.
SCORE_BANDS = (
    (85, 100, "Thriving — routine care only"),
    (60, 84, "Minor issues — easily corrected"),
    (30, 59, "At risk — will worsen without action"),
    (0, 29, "Severe decline, dying, or dead"),
)

# Shown next to the score so the number is never presented without its meaning.
SCORE_EXPLANATION = (
    "A 0-100 rating of the plant's overall condition, where 100 is thriving and 0 is dead. "
    "It is the model's judgement of the evidence you provided, not a measurement. "
    "85-100 thriving · 60-84 minor issues · 30-59 at risk · 0-29 severe decline."
)

CONFIDENCE_EXPLANATION = (
    "How sure the model is of this assessment, as reported by the model itself. "
    "Low means it is largely guessing; high means the evidence was clear and distinctive. "
    "Treat it as a rough self-assessment, not a calibrated probability."
)


def describe_score(score: int | None) -> str | None:
    """Plain-language meaning of a 0-100 health score."""
    if score is None:
        return None
    for low, high, label in SCORE_BANDS:
        if low <= score <= high:
            return label
    return None


RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": list(STATUSES)},
        "health_score": {"type": "integer", "minimum": 0, "maximum": 100},
        "confidence": {"type": "string", "enum": list(CONFIDENCE_LEVELS)},
        "confidence_reason": {"type": "string"},
        "plant_identification": {"type": "string"},
        "summary": {"type": "string"},
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "severity": {"type": "string", "enum": list(SEVERITIES)},
                    "evidence": {"type": "string"},
                },
                "required": ["name", "severity", "evidence"],
            },
        },
        "recommendations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "action": {"type": "string"},
                    "priority": {"type": "string", "enum": list(PRIORITIES)},
                    "details": {"type": "string"},
                },
                "required": ["action", "priority", "details"],
            },
        },
        "missing_information": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "status",
        "health_score",
        "confidence",
        "confidence_reason",
        "summary",
        "issues",
        "recommendations",
    ],
}


class AIUnavailableError(RuntimeError):
    """The local model could not be reached or did not return a usable answer."""


class OllamaClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        timeout: int = 180,
        auto_pull: bool = True,
        pull_timeout: int = 1800,
        keep_alive: str = "30m",
        num_predict: int = 700,
        num_ctx: int = 4096,
        stub: bool = False,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = "stub:vision" if stub else model
        self.stub = stub
        self.timeout = timeout
        self.auto_pull = auto_pull
        self.pull_timeout = pull_timeout
        # Keeping the model resident avoids a multi-second reload on every request.
        self.keep_alive = keep_alive
        self.num_predict = num_predict
        self.num_ctx = num_ctx
        self._model_ready = False

    # -- infrastructure -------------------------------------------------

    def ping(self) -> bool:
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=5)
            response.raise_for_status()
            return True
        except requests.RequestException:
            return False

    def available_models(self) -> list[str]:
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=5)
            response.raise_for_status()
            return [m.get("name", "") for m in response.json().get("models", [])]
        except (requests.RequestException, ValueError):
            return []

    def ensure_model(self) -> None:
        """Pull the configured model if the Ollama instance does not have it yet."""
        if self._model_ready:
            return

        models = self.available_models()
        if any(name == self.model or name.startswith(f"{self.model}:") for name in models):
            self._model_ready = True
            return

        if not self.auto_pull:
            raise AIUnavailableError(
                f"Model '{self.model}' is not available on the local AI instance and "
                "automatic pulling is disabled."
            )

        logger.info("Pulling model %s from Ollama, this may take a while...", self.model)
        try:
            response = requests.post(
                f"{self.base_url}/api/pull",
                json={"model": self.model, "stream": False},
                timeout=self.pull_timeout,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise AIUnavailableError(
                f"Could not pull model '{self.model}' from the local AI instance: {exc}"
            ) from exc

        self._model_ready = True

    # -- inference ------------------------------------------------------

    def _payload(
        self,
        description: str | None,
        image_b64: str | None,
        plant_ref: str | None,
        stream: bool,
    ) -> dict:
        message: dict = {
            "role": "user",
            "content": _build_prompt(description, plant_ref, has_image=bool(image_b64)),
        }
        if image_b64:
            message["images"] = [image_b64]

        return {
            "model": self.model,
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}, message],
            "stream": stream,
            "format": RESPONSE_SCHEMA,
            "keep_alive": self.keep_alive,
            "options": {
                "temperature": 0.2,
                # Bound the response length; the schema only needs a few short fields.
                "num_predict": self.num_predict,
                "num_ctx": self.num_ctx,
            },
        }

    def assess(
        self,
        description: str | None = None,
        image_b64: str | None = None,
        plant_ref: str | None = None,
    ) -> dict:
        if not description and not image_b64:
            raise ValueError("An image or a text description is required.")

        if self.stub:
            result = parse_content(_stub_content(description or ""))
            result["duration_ms"] = 900
            return result

        self.ensure_model()
        payload = self._payload(description, image_b64, plant_ref, stream=False)

        started = time.monotonic()
        try:
            response = requests.post(
                f"{self.base_url}/api/chat", json=payload, timeout=self.timeout
            )
            response.raise_for_status()
            body = response.json()
        except requests.RequestException as exc:
            raise AIUnavailableError(
                f"Could not reach the local AI instance at {self.base_url}: {exc}"
            ) from exc
        except ValueError as exc:
            raise AIUnavailableError("The local AI instance returned an invalid response.") from exc

        duration_ms = int((time.monotonic() - started) * 1000)
        logger.info(
            "assessment inference took %sms (model=%s, eval_count=%s)",
            duration_ms,
            self.model,
            body.get("eval_count"),
        )

        content = (body.get("message") or {}).get("content", "")
        normalised = parse_content(content)
        normalised["duration_ms"] = duration_ms
        return normalised

    def assess_stream(
        self,
        description: str | None = None,
        image_b64: str | None = None,
        plant_ref: str | None = None,
    ):
        """Yield progress events while the model composes its assessment.

        Emits ``{"type": "progress", ...}`` as text arrives, then exactly one
        ``{"type": "result", "result": ...}`` or ``{"type": "error", "message": ...}``.
        """

        if not description and not image_b64:
            yield {"type": "error", "message": "An image or a text description is required."}
            return

        if self.stub:
            yield from _stub_assess_stream(description or "")
            return

        try:
            self.ensure_model()
        except AIUnavailableError as exc:
            yield {"type": "error", "message": str(exc)}
            return

        payload = self._payload(description, image_b64, plant_ref, stream=True)
        started = time.monotonic()
        content = ""

        try:
            with requests.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=self.timeout,
                stream=True,
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines(decode_unicode=True):
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except ValueError:
                        continue

                    content += (chunk.get("message") or {}).get("content", "")
                    yield {
                        "type": "progress",
                        "field": _current_field(content),
                        "summary": _partial_string(content, "summary"),
                        "chars": len(content),
                        "elapsed_ms": int((time.monotonic() - started) * 1000),
                    }

                    if chunk.get("done"):
                        break
        except requests.RequestException as exc:
            yield {
                "type": "error",
                "message": f"Could not reach the local AI instance at {self.base_url}: {exc}",
            }
            return

        duration_ms = int((time.monotonic() - started) * 1000)
        try:
            result = parse_content(content)
        except AIUnavailableError as exc:
            yield {"type": "error", "message": str(exc)}
            return

        result["duration_ms"] = duration_ms
        yield {"type": "result", "result": result}


# --------------------------------------------------------------------------- #
# Showcase stub (AI_STUB=1) - canned assessments, no vision model call         #
# --------------------------------------------------------------------------- #

_STUB_AT_RISK = {
    "status": "at_risk",
    "health_score": 58,
    "confidence": "medium",
    "confidence_reason": "The description is clear but a close-up photo would confirm the cause.",
    "plant_identification": "Tomato (Solanum lycopersicum), based on the description.",
    "summary": "Lower leaves are yellowing while the newer growth stays green - an early "
    "sign of a nitrogen shortfall rather than disease.",
    "issues": [
        {
            "name": "Lower-leaf chlorosis",
            "severity": "medium",
            "evidence": "Yellowing described on the oldest leaves first, veins still green.",
        }
    ],
    "recommendations": [
        {
            "action": "Feed with a balanced liquid fertiliser",
            "priority": "high",
            "details": "Apply at half strength now and again in two weeks.",
        },
        {
            "action": "Mulch and keep watering even",
            "priority": "medium",
            "details": "Uneven moisture makes nutrient uptake worse.",
        },
    ],
    "missing_information": ["A close-up photo of an affected leaf", "Recent feeding history"],
}

_STUB_HEALTHY = {
    "status": "healthy",
    "health_score": 88,
    "confidence": "medium",
    "confidence_reason": "Nothing in the description points to a problem.",
    "plant_identification": "Leafy vegetable, based on the description.",
    "summary": "The plant sounds healthy - good colour and steady growth, no issues described.",
    "issues": [],
    "recommendations": [
        {
            "action": "Keep the current routine",
            "priority": "low",
            "details": "Consistent watering and a fortnightly feed are enough.",
        }
    ],
    "missing_information": ["A photo would let the model check leaf colour directly"],
}

_STUB_PROBLEM_WORDS = (
    "yellow", "spot", "wilt", "brown", "curl", "pest", "mold", "mould",
    "hole", "droop", "dying", "black", "rot",
)


def _stub_content(description: str) -> str:
    low = description.lower()
    result = _STUB_HEALTHY if not any(w in low for w in _STUB_PROBLEM_WORDS) else _STUB_AT_RISK
    return json.dumps(result)


def _stub_assess_stream(description: str):
    """Mimic `assess_stream` fast: a few progress ticks, then the result."""
    result = _STUB_HEALTHY if not any(
        w in description.lower() for w in _STUB_PROBLEM_WORDS
    ) else _STUB_AT_RISK
    steps = [
        ("status", "Deciding overall status", 120),
        ("health_score", "Scoring the plant's condition", 240),
        ("summary", "Writing the summary", 380),
        ("issues", "Listing observed issues", 520),
        ("recommendations", "Working out recommendations", 660),
    ]
    for _key, label, chars in steps:
        time.sleep(0.28)
        yield {
            "type": "progress",
            "field": label,
            "summary": result["summary"] if chars >= 380 else "",
            "chars": chars,
            "elapsed_ms": chars,
        }
    result = dict(result)
    result["duration_ms"] = 900
    yield {"type": "result", "result": normalise_result(result)}


def parse_content(content: str) -> dict:
    """Parse and normalise a completed model response body."""
    try:
        result = json.loads(content)
    except (TypeError, ValueError) as exc:
        raise AIUnavailableError(
            "The local AI model did not return valid JSON. Try again, or use a model "
            "that supports structured output."
        ) from exc

    if not isinstance(result, dict):
        raise AIUnavailableError("The local AI model returned an unexpected result shape.")

    return normalise_result(result)


# Human-readable labels for the schema keys, used to narrate streaming progress.
FIELD_LABELS = {
    "status": "Deciding overall status",
    "health_score": "Scoring the plant's condition",
    "confidence": "Judging its confidence",
    "confidence_reason": "Explaining that confidence",
    "plant_identification": "Identifying the plant",
    "summary": "Writing the summary",
    "issues": "Listing observed issues",
    "recommendations": "Working out recommendations",
    "missing_information": "Noting what else would help",
}

_KEY_RE = re.compile(r'"([a-z_]+)"\s*:')


def _current_field(content: str) -> str:
    """Best-effort label for whichever schema field is being generated."""
    matches = _KEY_RE.findall(content)
    for key in reversed(matches):
        if key in FIELD_LABELS:
            return FIELD_LABELS[key]
    return "Thinking"


def _partial_string(content: str, key: str) -> str:
    """Extract a string value from partial JSON, even before it is closed."""
    marker = f'"{key}"'
    start = content.find(marker)
    if start == -1:
        return ""
    quote = content.find('"', content.find(":", start + len(marker)))
    if quote == -1:
        return ""

    out = []
    i = quote + 1
    while i < len(content):
        char = content[i]
        if char == "\\" and i + 1 < len(content):
            out.append(content[i + 1])
            i += 2
            continue
        if char == '"':
            break
        out.append(char)
        i += 1
    return "".join(out)


def _build_prompt(
    description: str | None, plant_ref: str | None, has_image: bool = False
) -> str:
    if has_image and description:
        evidence = "one photo and a written description"
    elif has_image:
        evidence = "one photo, and no written description"
    else:
        evidence = "a written description only, and no photo"

    parts = [f"EVIDENCE PROVIDED: {evidence}."]
    if plant_ref:
        parts.append(f"The gardener refers to this plant as: {plant_ref}")
    if description:
        parts.append(f"Gardener's description of the plant and its care:\n{description}")
    else:
        parts.append("No written description was provided; rely on the photo.")
    parts.append(
        "Assess the plant's health and give recommendations to improve it if needed. "
        "When explaining your confidence, refer only to the evidence listed above."
    )
    return "\n\n".join(parts)


def normalise_result(result: dict) -> dict:
    """Coerce a model response into the shape the rest of the service relies on."""

    status = str(result.get("status", "unknown")).strip().lower().replace(" ", "_")
    if status not in STATUSES:
        status = "unknown"

    health_score = _clamp_int(result.get("health_score"), 0, 100)
    # An "unknown" verdict has no meaningful score to report.
    if status == "unknown":
        health_score = None

    confidence = str(result.get("confidence", "")).strip().lower()
    if confidence not in CONFIDENCE_LEVELS:
        confidence = None
    # A verdict of "unknown" is by definition not a confident one.
    if status == "unknown" and confidence == "high":
        confidence = "low"

    issues = []
    for issue in result.get("issues") or []:
        if not isinstance(issue, dict):
            continue
        name = str(issue.get("name", "")).strip()
        if not name:
            continue
        severity = str(issue.get("severity", "")).strip().lower()
        issues.append(
            {
                "name": name,
                "severity": severity if severity in SEVERITIES else "medium",
                "evidence": str(issue.get("evidence", "")).strip(),
            }
        )

    recommendations = []
    for rec in result.get("recommendations") or []:
        if not isinstance(rec, dict):
            continue
        action = str(rec.get("action", "")).strip()
        if not action:
            continue
        priority = str(rec.get("priority", "")).strip().lower()
        recommendations.append(
            {
                "action": action,
                "priority": priority if priority in PRIORITIES else "medium",
                "details": str(rec.get("details", "")).strip(),
            }
        )

    missing = [
        str(item).strip()
        for item in (result.get("missing_information") or [])
        if str(item).strip()
    ]

    return {
        "status": status,
        "health_score": health_score,
        "score_band": describe_score(health_score),
        "confidence": confidence,
        "confidence_reason": str(result.get("confidence_reason", "")).strip() or None,
        "plant_identification": str(result.get("plant_identification", "")).strip() or None,
        "summary": str(result.get("summary", "")).strip(),
        "issues": issues[:MAX_LIST_ITEMS],
        "recommendations": recommendations[:MAX_LIST_ITEMS],
        "missing_information": missing[:MAX_LIST_ITEMS],
    }


def _clamp_int(value, low: int, high: int) -> int | None:
    try:
        return max(low, min(high, int(round(float(value)))))
    except (TypeError, ValueError):
        return None

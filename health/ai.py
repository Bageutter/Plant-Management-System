"""Client for the locally hosted AI (Ollama) used to assess plant health.

The service deliberately keeps all inference local: images and descriptions are
sent to an Ollama instance on the local network and never to a third party.
"""

from __future__ import annotations

import json
import logging
import time

import requests

logger = logging.getLogger(__name__)

STATUSES = ("healthy", "at_risk", "unhealthy", "unknown")
SEVERITIES = ("low", "medium", "high")
PRIORITIES = ("low", "medium", "high")
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
    "If the status is \"unknown\", set health_score to 0; it is not shown to the user."
)

# Bands used to explain the score in the UI. Kept in sync with SYSTEM_PROMPT.
SCORE_BANDS = (
    (85, 100, "Thriving — routine care only"),
    (60, 84, "Minor issues — easily corrected"),
    (30, 59, "At risk — will worsen without action"),
    (0, 29, "Severe decline, dying, or dead"),
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
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
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

    def assess(
        self,
        description: str | None = None,
        image_b64: str | None = None,
        plant_ref: str | None = None,
    ) -> dict:
        if not description and not image_b64:
            raise ValueError("An image or a text description is required.")

        self.ensure_model()

        message: dict = {"role": "user", "content": _build_prompt(description, plant_ref)}
        if image_b64:
            message["images"] = [image_b64]

        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}, message],
            "stream": False,
            "format": RESPONSE_SCHEMA,
            "keep_alive": self.keep_alive,
            "options": {
                "temperature": 0.2,
                # Bound the response length; the schema only needs a few short fields.
                "num_predict": self.num_predict,
                "num_ctx": self.num_ctx,
            },
        }

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
        try:
            result = json.loads(content)
        except (TypeError, ValueError) as exc:
            raise AIUnavailableError(
                "The local AI model did not return valid JSON. Try again, or use a model "
                "that supports structured output."
            ) from exc

        if not isinstance(result, dict):
            raise AIUnavailableError("The local AI model returned an unexpected result shape.")

        normalised = normalise_result(result)
        normalised["duration_ms"] = duration_ms
        return normalised


def _build_prompt(description: str | None, plant_ref: str | None) -> str:
    parts = []
    if plant_ref:
        parts.append(f"The gardener refers to this plant as: {plant_ref}")
    if description:
        parts.append(f"Gardener's description of the plant and its care:\n{description}")
    else:
        parts.append("No written description was provided; rely on the photo.")
    parts.append(
        "Assess the plant's health and give recommendations to improve it if needed."
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

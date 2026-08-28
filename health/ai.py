"""Client for the locally hosted AI (Ollama) used to assess plant health.

The service deliberately keeps all inference local: images and descriptions are
sent to an Ollama instance on the local network and never to a third party.
"""

from __future__ import annotations

import json
import logging

import requests

logger = logging.getLogger(__name__)

STATUSES = ("healthy", "at_risk", "unhealthy", "unknown")
SEVERITIES = ("low", "medium", "high")
PRIORITIES = ("low", "medium", "high")

SYSTEM_PROMPT = (
    "You are a horticultural plant health analyst for a small home garden system. "
    "You are given a photo of a plant, a written description of it, or both. "
    "Assess whether the plant is healthy and, when it is not, explain what should be "
    "done to improve its health.\n"
    "Rules:\n"
    "- Base your assessment only on the evidence provided. Do not invent observations.\n"
    "- If the evidence is too thin to judge, use status \"unknown\", a low confidence, "
    "and ask for what extra information or photos would help.\n"
    "- Recommendations must be concrete, actionable gardening steps a home gardener can "
    "carry out (e.g. \"reduce watering to twice a week until the top 3cm of soil dries\").\n"
    "- Prefer the least invasive effective action first.\n"
    "- Respond only with JSON matching the requested schema."
)

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": list(STATUSES)},
        "health_score": {"type": "integer", "minimum": 0, "maximum": 100},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
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
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.auto_pull = auto_pull
        self.pull_timeout = pull_timeout
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
            "options": {"temperature": 0.2},
        }

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

        return normalise_result(result)


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
    confidence = _clamp_float(result.get("confidence"), 0.0, 1.0)

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
        "confidence": confidence,
        "plant_identification": str(result.get("plant_identification", "")).strip() or None,
        "summary": str(result.get("summary", "")).strip(),
        "issues": issues,
        "recommendations": recommendations,
        "missing_information": missing,
    }


def _clamp_int(value, low: int, high: int) -> int | None:
    try:
        return max(low, min(high, int(round(float(value)))))
    except (TypeError, ValueError):
        return None


def _clamp_float(value, low: float, high: float) -> float | None:
    try:
        return max(low, min(high, round(float(value), 2)))
    except (TypeError, ValueError):
        return None

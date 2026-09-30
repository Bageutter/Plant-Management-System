"""Client for the locally hosted AI (Ollama) used to assess plant health.

The service deliberately keeps all inference local: images and descriptions are
sent to an Ollama instance on the local network and never to a third party.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from datetime import datetime, timezone

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
        # Startup preload (see preload()). Reported on /healthz.
        self.preload_state: dict = {"status": "not_started", "attempts": 0, "detail": None}
        self._preload_lock = threading.Lock()

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

    # -- startup preload -----------------------------------------------

    def preload(self) -> None:
        """Load the model into Ollama's memory so the first assessment is warm.

        Ollama loads a model on the first request that names it and keeps it
        resident for ``keep_alive``; a cold load costs several seconds to tens of
        seconds on top of inference. Sending a chat request with no messages is
        Ollama's documented way to trigger that load without generating anything.
        Pulls the model first if it is missing and pulling is allowed.
        """

        self.ensure_model()
        started = time.monotonic()
        try:
            response = requests.post(
                f"{self.base_url}/api/chat",
                json={"model": self.model, "messages": [], "keep_alive": self.keep_alive},
                timeout=self.timeout,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise AIUnavailableError(
                f"Could not preload model '{self.model}' on the local AI instance: {exc}"
            ) from exc
        duration_ms = int((time.monotonic() - started) * 1000)
        logger.info("model %s loaded in %sms (keep_alive=%s)", self.model, duration_ms, self.keep_alive)
        self._set_preload(
            "loaded",
            detail=f"loaded in {duration_ms / 1000:.1f}s",
            duration_ms=duration_ms,
            loaded_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )

    def start_preload(self, *, retries: int = 12, delay: float = 5.0) -> threading.Thread:
        """Preload in a daemon thread so startup is never blocked by the model.

        Ollama may still be starting when this service comes up (compose only
        waits for the container to exist), so failures are retried with a growing
        delay. Every outcome is recorded in ``preload_state`` and never raised.
        """

        def run() -> None:
            wait = delay
            for attempt in range(1, max(1, retries) + 1):
                self._set_preload("loading", attempts=attempt, detail=f"attempt {attempt} of {retries}")
                try:
                    self.preload()
                    return
                except (AIUnavailableError, requests.RequestException) as exc:
                    logger.warning("model preload attempt %s/%s failed: %s", attempt, retries, exc)
                    self._set_preload("retrying", attempts=attempt, detail=str(exc))
                if attempt < retries:
                    time.sleep(wait)
                    wait = min(wait * 1.5, 60.0)
            self._set_preload("failed", detail=f"gave up after {retries} attempt(s); the first request will load it")

        self._set_preload("pending", attempts=0, detail="starting")
        thread = threading.Thread(target=run, name="ollama-preload", daemon=True)
        thread.start()
        return thread

    def _set_preload(self, status: str, **fields) -> None:
        with self._preload_lock:
            self.preload_state = {**self.preload_state, **fields, "status": status}

    # -- inference ------------------------------------------------------

    def _payload(
        self,
        description: str | None,
        image_b64: str | None,
        plant_ref: str | None,
        stream: bool,
        feedback: str | None = None,
        history: list[dict] | None = None,
    ) -> dict:
        message: dict = {
            "role": "user",
            "content": _build_prompt(
                description,
                plant_ref,
                has_image=bool(image_b64),
                feedback=feedback,
                history=history,
            ),
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
        feedback: str | None = None,
        history: list[dict] | None = None,
    ) -> dict:
        """One structured assessment.

        ``feedback`` is a reviewer's guidance on a previous draft (the loop's
        REPEAT → REASON hand-off); ``history`` lists this plant's earlier
        assessments, given to the model as context only.
        """

        if not description and not image_b64:
            raise ValueError("An image or a text description is required.")

        self.ensure_model()
        payload = self._payload(
            description, image_b64, plant_ref, stream=False, feedback=feedback, history=history
        )

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
        feedback: str | None = None,
        history: list[dict] | None = None,
    ):
        """Yield progress events while the model composes its assessment.

        Emits ``{"type": "progress", ...}`` as text arrives, then exactly one
        ``{"type": "result", "result": ...}`` or ``{"type": "error", "message": ...}``.
        """

        if not description and not image_b64:
            yield {"type": "error", "message": "An image or a text description is required."}
            return

        try:
            self.ensure_model()
        except AIUnavailableError as exc:
            yield {"type": "error", "message": str(exc)}
            return

        payload = self._payload(
            description, image_b64, plant_ref, stream=True, feedback=feedback, history=history
        )
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
    description: str | None,
    plant_ref: str | None,
    has_image: bool = False,
    feedback: str | None = None,
    history: list[dict] | None = None,
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
    if history:
        lines = "\n".join(
            f"- {h.get('created_at', '')}: {h.get('status', 'unknown')}"
            + (f", score {h['health_score']}" if h.get("health_score") is not None else "")
            + (f" — {h['summary']}" if h.get("summary") else "")
            for h in history
        )
        parts.append(
            "Earlier assessments recorded for this plant, for context only. They are not "
            "current observations; do not repeat them as evidence, but you may note a "
            f"change since then:\n{lines}"
        )
    parts.append(
        "Assess the plant's health and give recommendations to improve it if needed. "
        "When explaining your confidence, refer only to the evidence listed above."
    )
    if feedback:
        parts.append(
            "An independent reviewer checked your previous draft of this assessment and "
            f"asked for the following correction. Apply it:\n{feedback}"
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

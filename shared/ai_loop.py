"""Runtime agentic AI workflow: Plan -> Act -> Observe -> Adapt.

Every answer from the chat features (almanac, virtual garden) is produced by an
iterating loop:

  PLAN     assemble the grounding context (records / garden snapshot / weather /
           history) the model is allowed to use
  ACT      a proposer model drafts an answer from that context (+ any reviewer
           feedback carried from the previous iteration)
  OBSERVE  a second, independent model reviews the draft against the same
           grounding and returns approved / revise + concrete guidance
  ADAPT    approved -> return it; revise -> feed the guidance back into ACT and
           loop, up to `max_iterations`

This mirrors the build-time reviewer in `tools/ai-dev/pipeline.py`, moved into
the request path. Every phase of every run is logged three ways: the service's
stdout logger, an appended JSONL, and a per-run markdown transcript. See
`docs/agentic-ai-workflow.md`.

Single canonical copy. Mounted into the almanac/vgarden containers at
`/app/ai_loop.py`; importable locally via a `../shared` sys.path entry. Pure
stdlib so it has no packaging/deploy story of its own.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable
from urllib import error, request

log = logging.getLogger("ai_loop")

# Mirrors tools/ai-dev/prompts/observe.txt, adapted to review a chat answer.
PROMPT_REVIEW = """You are an independent reviewer of an AI assistant's DRAFT answer.

Every value in GROUNDING is a fact the assistant IS allowed to state — quantities,
names, dates and weather values in the grounding are supported, and restating or
rephrasing them is correct, not an error.

Return "revise" only when one of these is clearly true:
- The draft asserts something that is absent from the grounding AND not a plain
  restatement of it, or that directly contradicts a grounding value.
- The question needs a fact the grounding does not contain, and the draft guesses
  or answers confidently instead of saying the information isn't available.
- The draft does not answer the user's question, or goes off-topic.

If the draft only uses facts that appear in the grounding and answers the
question, return "approved". When genuinely unsure, return "approved".

Return JSON only, exactly these keys:
{
  "verdict": "approved" or "revise",
  "issues": ["short, specific problem", ...],   // empty list when approved
  "guidance": "one concrete instruction for the next draft"   // "" when approved
}"""


class LoopError(RuntimeError):
    """The loop could not run (e.g. the review model is unreachable)."""


# --------------------------------------------------------------------------- #
# Ollama helpers                                                              #
# --------------------------------------------------------------------------- #

def _ollama_post(base_url: str, path: str, payload: dict, timeout: int) -> dict:
    req = request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def ensure_model(base_url: str, model: str, auto_pull: bool, pull_timeout: int = 1800) -> None:
    """Confirm `model` is on the Ollama instance, pulling it once if allowed.

    Same contract as the `_ensure_model` methods in almanac/ai.py and
    vgarden/ai.py; kept here so the reviewer can guarantee its own model.
    """
    try:
        with request.urlopen(f"{base_url.rstrip('/')}/api/tags", timeout=10) as response:
            names = {m.get("name", "") for m in json.loads(response.read()).get("models", [])}
    except (error.URLError, TimeoutError, ValueError) as exc:
        raise LoopError(f"Cannot reach Ollama at {base_url}") from exc

    if model in names or f"{model}:latest" in names:
        return
    if not auto_pull:
        raise LoopError(
            f"Review model '{model}' is not on the Ollama instance. "
            f"Run `ollama pull {model}` or set OLLAMA_AUTO_PULL=true."
        )
    try:
        _ollama_post(base_url, "/api/pull", {"model": model, "stream": False}, pull_timeout)
    except (error.URLError, TimeoutError, ValueError) as exc:
        raise LoopError(f"Could not pull review model '{model}'") from exc


# --------------------------------------------------------------------------- #
# Reviewer (the OBSERVE step)                                                 #
# --------------------------------------------------------------------------- #

class Reviewer:
    """Independent second model that reviews each draft answer."""

    def __init__(
        self,
        base_url: str,
        model: str,
        timeout: int = 120,
        auto_pull: bool = False,
        num_predict: int = 300,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.auto_pull = auto_pull
        self.num_predict = num_predict
        self._ready = False

    def ensure_ready(self) -> None:
        if not self._ready:
            ensure_model(self.base_url, self.model, self.auto_pull)
            self._ready = True

    def review(self, question: str, grounding: dict, draft: str) -> dict:
        self.ensure_ready()
        user = (
            "GROUNDING (the complete set of facts the assistant may use — every "
            "value here counts as supported):\n"
            f"{json.dumps(grounding, ensure_ascii=False, indent=2)}\n\n"
            f"USER QUESTION:\n{question}\n\n"
            f"DRAFT ANSWER TO REVIEW:\n{draft}"
        )
        try:
            body = _ollama_post(
                self.base_url,
                "/api/chat",
                {
                    "model": self.model,
                    "stream": False,
                    "format": "json",
                    "messages": [
                        {"role": "system", "content": PROMPT_REVIEW},
                        {"role": "user", "content": user},
                    ],
                    "options": {"temperature": 0, "num_predict": self.num_predict},
                },
                self.timeout,
            )
            result = json.loads(body["message"]["content"])
        except (error.URLError, TimeoutError, ValueError, KeyError, TypeError) as exc:
            raise LoopError(f"Reviewer call failed: {exc}") from exc

        verdict = "approved" if str(result.get("verdict", "")).lower() == "approved" else "revise"
        issues = [str(i).strip() for i in (result.get("issues") or []) if str(i).strip()]
        guidance = str(result.get("guidance") or "").strip()
        return {"verdict": verdict, "issues": issues, "guidance": guidance}


# --------------------------------------------------------------------------- #
# Logging: stdout + JSONL + markdown transcript                               #
# --------------------------------------------------------------------------- #

class LoopLogger:
    """Writes each phase to three sinks so a run can always be reconstructed."""

    def __init__(self, service: str, log_dir: str, run_id: str, question: str):
        self.service = service
        self.run_id = run_id
        self.question = question
        self.started = time.monotonic()
        self.events: list[dict] = []

        self.jsonl_path = os.path.join(log_dir, f"{service}.jsonl")
        report_dir = os.path.join(log_dir, "reports", service)
        os.makedirs(report_dir, exist_ok=True)
        self.transcript_path = os.path.join(report_dir, f"{run_id}.md")

        with open(self.transcript_path, "w", encoding="utf-8") as fh:
            fh.write(
                f"# Agentic loop run `{run_id}`\n\n"
                f"- **service:** {service}\n"
                f"- **started:** {datetime.now(timezone.utc).isoformat(timespec='seconds')}\n"
                f"- **question:** {question}\n\n"
                "Workflow: **Plan → Act → Observe → Adapt**\n"
            )

    _BLOCK_KEYS = ("draft", "answer", "body")  # rendered as a code block, not a bullet

    def phase(self, name: str, data: dict, *, body: str | None = None) -> None:
        elapsed_ms = int((time.monotonic() - self.started) * 1000)
        if body is not None:
            data = {**data, "answer": body}
        event = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "run_id": self.run_id,
            "service": self.service,
            "phase": name,
            "elapsed_ms": elapsed_ms,
            **data,
        }
        self.events.append(event)

        log.info(
            "[%s] %s %s",
            self.run_id,
            name.upper(),
            " ".join(
                f"{k}={v}"
                for k, v in data.items()
                if k not in ("question", *self._BLOCK_KEYS)
            ),
        )
        with open(self.jsonl_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")
        with open(self.transcript_path, "a", encoding="utf-8") as fh:
            fh.write(f"\n## {name.upper()}  ·  +{elapsed_ms} ms\n\n")
            for key, value in data.items():
                if key in self._BLOCK_KEYS:
                    fh.write(f"\n**{key}:**\n\n```\n{value}\n```\n\n")
                else:
                    fh.write(f"- **{key}:** {value}\n")


# --------------------------------------------------------------------------- #
# Result                                                                      #
# --------------------------------------------------------------------------- #

@dataclass
class LoopResult:
    answer: str
    iterations: int
    verdict: str  # "approved" | "revised_capped" | "fallback"
    run_id: str
    transcript_path: str
    trace: list[dict] = field(default_factory=list)

    @property
    def reviewed(self) -> bool:
        return self.verdict != "fallback"


# --------------------------------------------------------------------------- #
# The loop                                                                    #
# --------------------------------------------------------------------------- #

# drafter(question, grounding, feedback) -> str
Drafter = Callable[[str, dict, "str | None"], str]
# build_context() -> (grounding_dict, plan_summary_dict)
ContextBuilder = Callable[[], "tuple[dict, dict]"]


class AgenticLoop:
    def __init__(
        self,
        service: str,
        drafter: Drafter,
        reviewer: Reviewer | None,
        log_dir: str,
        max_iterations: int = 2,
    ):
        self.service = service
        self.drafter = drafter
        self.reviewer = reviewer
        self.log_dir = log_dir
        self.max_iterations = max(1, max_iterations)

    def run(self, question: str, build_context: ContextBuilder) -> LoopResult:
        run_id = "{}-{}-{}".format(
            self.service,
            datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S"),
            uuid.uuid4().hex[:6],
        )
        os.makedirs(self.log_dir, exist_ok=True)
        logger = LoopLogger(self.service, self.log_dir, run_id, question)

        # -- PLAN ----------------------------------------------------------
        grounding, plan_summary = build_context()
        logger.phase("plan", {"question": question, **plan_summary})

        # No reviewer available -> single-shot, clearly logged as a fallback.
        if self.reviewer is None:
            answer = self.drafter(question, grounding, None)
            logger.phase(
                "fallback",
                {"reason": "no review model configured", "iterations": 1},
                body=answer,
            )
            return LoopResult(answer, 1, "fallback", run_id, logger.transcript_path, logger.events)

        feedback: str | None = None
        answer = ""
        for i in range(1, self.max_iterations + 1):
            # -- ACT -----------------------------------------------------
            t0 = time.monotonic()
            answer = self.drafter(question, grounding, feedback)
            logger.phase(
                "act",
                {
                    "iteration": i,
                    "carried_feedback": feedback or "(none)",
                    "draft": answer,
                    "draft_chars": len(answer),
                    "ms": int((time.monotonic() - t0) * 1000),
                },
            )

            # -- OBSERVE -----------------------------------------------
            t0 = time.monotonic()
            try:
                review = self.reviewer.review(question, grounding, answer)
            except LoopError as exc:
                logger.phase("fallback", {"reason": str(exc), "iteration": i}, body=answer)
                return LoopResult(
                    answer, i, "fallback", run_id, logger.transcript_path, logger.events
                )
            logger.phase(
                "observe",
                {
                    "iteration": i,
                    "verdict": review["verdict"],
                    "issues": "; ".join(review["issues"]) or "(none)",
                    "ms": int((time.monotonic() - t0) * 1000),
                },
            )

            # -- ADAPT -----------------------------------------------
            if review["verdict"] == "approved":
                logger.phase("adapt", {"iteration": i, "decision": "accept"})
                return LoopResult(
                    answer, i, "approved", run_id, logger.transcript_path, logger.events
                )

            feedback = review["guidance"] or "; ".join(review["issues"]) or "Revise the answer."
            if i < self.max_iterations:
                logger.phase(
                    "adapt", {"iteration": i, "decision": "revise", "guidance": feedback}
                )

        logger.phase(
            "adapt",
            {"iteration": self.max_iterations, "decision": "stop_capped"},
            body=answer,
        )
        return LoopResult(
            answer, self.max_iterations, "revised_capped", run_id, logger.transcript_path, logger.events
        )


def replay_trace_to_logs(
    log_dir: str, service: str, run_id: str, question: str, trace: list[dict]
) -> str:
    """Write an already-computed phase trace (seeded demo data) to the JSONL +
    markdown transcript sinks, so `tools/ai-loop/view.py` shows it on a fresh
    boot without a live model call. Returns the transcript path. Skips work if
    this run_id is already in the JSONL.
    """
    report_dir = os.path.join(log_dir, "reports", service)
    os.makedirs(report_dir, exist_ok=True)
    jsonl_path = os.path.join(log_dir, f"{service}.jsonl")
    transcript_path = os.path.join(report_dir, f"{run_id}.md")

    if os.path.exists(jsonl_path):
        with open(jsonl_path, encoding="utf-8") as fh:
            if f'"{run_id}"' in fh.read():
                return transcript_path

    with open(transcript_path, "w", encoding="utf-8") as fh:
        fh.write(
            f"# Agentic loop run `{run_id}`\n\n"
            f"- **service:** {service}\n"
            f"- **question:** {question}\n\n"
            "Workflow: **Plan → Act → Observe → Adapt**  ·  _seeded demo run_\n"
        )
    with open(jsonl_path, "a", encoding="utf-8") as jf, \
            open(transcript_path, "a", encoding="utf-8") as tf:
        for event in trace:
            row = {"service": service, "run_id": run_id, **event}
            jf.write(json.dumps(row, ensure_ascii=False) + "\n")
            head = event["phase"].upper()
            if event.get("iteration"):
                head += f"  ·  #{event['iteration']}"
            tf.write(f"\n## {head}\n\n")
            for key, value in event.items():
                if key in ("phase", "iteration", "run_id", "service", "ts"):
                    continue
                if key in LoopLogger._BLOCK_KEYS:
                    tf.write(f"\n**{key}:**\n\n```\n{value}\n```\n\n")
                else:
                    tf.write(f"- **{key}:** {value}\n")
    return transcript_path


def build_reviewer(config: dict) -> Reviewer | None:
    """Construct a Reviewer from app config, or None when `OLLAMA_REVIEW_MODEL`
    is unset (reviewing disabled -> the loop runs single-shot).

    Model availability is *not* checked here (that would block app startup on a
    pull). The loop catches a `LoopError` from the first `review()` call and
    degrades to single-shot, logged as a `fallback` phase — a reviewer outage
    never breaks the chat.
    """
    model = config.get("OLLAMA_REVIEW_MODEL")
    if not model:
        return None
    return Reviewer(
        base_url=config.get("OLLAMA_URL", "http://localhost:11434"),
        model=model,
        timeout=config.get("OLLAMA_TIMEOUT", 120),
        auto_pull=config.get("OLLAMA_AUTO_PULL", False),
    )

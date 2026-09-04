"""'Discuss this assessment' follow-up chat.

Same shape as vgarden/garden_ai.py and almanac's chat: every reply runs through
the shared Plan -> Act -> Observe -> Adapt loop, the conversation is stored, and
each reply links to its loop trace.
"""

import os
import sys

from flask import Blueprint, abort, current_app, render_template, request

from ai import AIUnavailableError
from extensions import db
from models import Assessment, AssessmentAILoopRun, AssessmentChatMessage
from routes import URL_PREFIX

_SHARED = os.path.join(os.path.abspath(os.path.dirname(__file__)), "..", "shared")
if os.path.isdir(_SHARED) and _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)

try:
    import ai_loop  # noqa: E402
except ImportError:
    ai_loop = None

bp = Blueprint("chat", __name__, url_prefix=URL_PREFIX)

CHAT_HISTORY_LIMIT = 20
MAX_QUESTION_LENGTH = 500


class _SingleShot:
    def __init__(self, answer):
        self.answer = answer
        self.iterations = 1
        self.verdict = "fallback"
        self.run_id = None
        self.transcript_path = ""
        self.trace = []


def _get_assessment(assessment_id: int) -> Assessment:
    assessment = db.session.get(Assessment, assessment_id)
    if assessment is None:
        abort(404)
    return assessment


def _history(assessment_id: int) -> list[AssessmentChatMessage]:
    messages = (
        AssessmentChatMessage.query.filter_by(assessment_id=assessment_id)
        .order_by(AssessmentChatMessage.id.desc())
        .limit(CHAT_HISTORY_LIMIT)
        .all()
    )
    return list(reversed(messages))


def _render_chat(assessment: Assessment, error: str | None = None):
    return render_template(
        "_chat_history.html",
        assessment=assessment,
        messages=_history(assessment.id),
        error=error,
    )


def _snapshot(assessment: Assessment) -> dict:
    return {
        "plant": assessment.plant_ref or assessment.plant_identification,
        "gardener_description": assessment.description,
        "notes": assessment.notes,
        "status": assessment.status,
        "health_score": assessment.health_score,
        "score_band": assessment.score_band,
        "confidence": assessment.confidence_level,
        "confidence_reason": assessment.confidence_reason,
        "summary": assessment.summary,
        "issues": assessment.issues,
        "recommendations": assessment.recommendations,
        "missing_information": assessment.missing_information,
        "had_photo": assessment.has_image,
    }


def _run_loop(question, build_context):
    chat_ai = current_app.extensions["health_chat_ai"]
    if ai_loop is None:
        grounding, _ = build_context()
        return _SingleShot(chat_ai.draft(question, grounding, None))
    loop = ai_loop.AgenticLoop(
        service="health",
        drafter=lambda q, g, fb: chat_ai.draft(q, g, fb),
        reviewer=current_app.extensions.get("ai_loop_reviewer"),
        log_dir=current_app.config["AI_LOOP_LOG_DIR"],
        max_iterations=current_app.config["AI_LOOP_MAX_ITERATIONS"],
    )
    return loop.run(question, build_context)


@bp.route("/assessments/<int:assessment_id>/chat", methods=["POST"])
def ask(assessment_id):
    assessment = _get_assessment(assessment_id)

    question = (request.form.get("question") or "").strip()
    if not question:
        return _render_chat(assessment, "Enter a question first."), 400
    if len(question) > MAX_QUESTION_LENGTH:
        return _render_chat(assessment, f"Keep it under {MAX_QUESTION_LENGTH} characters."), 400

    history = [{"role": m.role, "content": m.content} for m in _history(assessment_id)]

    def build_context():
        snapshot = _snapshot(assessment)
        grounding = {"assessment": snapshot, "conversation": history}
        plan_summary = {
            "status": snapshot["status"],
            "issues": len(snapshot["issues"]),
            "recommendations": len(snapshot["recommendations"]),
            "history_messages": len(history),
        }
        return grounding, plan_summary

    try:
        result = _run_loop(question, build_context)
    except AIUnavailableError:
        return _render_chat(
            assessment,
            "The local AI model is unavailable. Check that Ollama is running and try again.",
        ), 503

    user_msg = AssessmentChatMessage(assessment_id=assessment_id, role="user", content=question)
    assistant_msg = AssessmentChatMessage(
        assessment_id=assessment_id, role="assistant", content=result.answer
    )
    db.session.add_all([user_msg, assistant_msg])
    db.session.flush()
    if result.run_id:
        db.session.add(
            AssessmentAILoopRun(
                assessment_id=assessment_id,
                message_id=assistant_msg.id,
                run_id=result.run_id,
                question=question,
                final_answer=result.answer,
                iterations=result.iterations,
                verdict=result.verdict,
                transcript_path=result.transcript_path,
                trace=result.trace,
            )
        )
    db.session.commit()
    return _render_chat(assessment)


@bp.route("/assessments/<int:assessment_id>/chat/clear", methods=["POST"])
def clear(assessment_id):
    assessment = _get_assessment(assessment_id)
    AssessmentAILoopRun.query.filter_by(assessment_id=assessment_id).delete()
    AssessmentChatMessage.query.filter_by(assessment_id=assessment_id).delete()
    db.session.commit()
    return _render_chat(assessment)


@bp.route("/assessments/<int:assessment_id>/chat/loop/<int:run_id>")
def loop_trace(assessment_id, run_id):
    assessment = _get_assessment(assessment_id)
    run = db.session.get(AssessmentAILoopRun, run_id)
    if run is None or run.assessment_id != assessment.id:
        abort(404)
    return render_template("loop_trace.html", assessment=assessment, run=run)

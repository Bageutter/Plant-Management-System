"""Plant Health UI access to the shared local Multi-Agent Server (Release 2).

Frontend UI -> this backend -> Multi-Agent Server -> Planner -> Worker -> Reviewer
-> Human Review (on the assessment's page) -> result shown here.

- The browser only ever names a *local* ``HealthWorkflow`` row under an
  assessment; the Multi-Agent Server's workflow id is looked up from that row and
  never taken from client input.
- The evidence sent with a task is that one assessment and the same plant's
  earlier assessments. The shared server never reads health data itself.
- An assessment is an earlier AI opinion with a stated confidence, not a
  diagnosis, and the evidence says so.

A run makes three local model calls, which can outlast the proxy's timeout, so it
is started off the request thread and the page polls the workflow's status.
"""

from __future__ import annotations

import logging
import re
import threading

from flask import Blueprint, abort, current_app, jsonify, render_template, request
from sqlalchemy import func

from extensions import db
from integrations import IntegrationDisabled, IntegrationUnavailable, WorkflowConflict
from models import Assessment, HealthWorkflow
from routes import URL_PREFIX, _integration_error, _wants_html

logger = logging.getLogger(__name__)

bp = Blueprint("health_workflows", __name__, url_prefix=URL_PREFIX)

MAX_TASK_CHARS = 500
MAX_FEEDBACK_CHARS = 2000
MAX_PASSAGE_CHARS = 4000
HISTORY_LIMIT = 5
DECISIONS = ("accept", "partially_accept", "request_changes", "reject")
IN_PROGRESS = ("planning", "working", "reviewing")
FINAL = ("accepted", "partially_accepted", "rejected")
# The UI has no sign-in, so the decision is recorded against the web UI itself.
UI_REVIEWER_ID = "health-user-web"
# A JSON caller (e.g. scripts/test/multi-agent-health.sh) may name itself so the audit
# tells terminal and UI decisions apart. It is a label, not an identity check.
REVIEWER_ID_CHARS = re.compile(r"^[A-Za-z0-9._-]{1,100}$")

# Workflow ids this process is currently running. A runnable workflow that is not
# here (e.g. the service restarted mid-run) is offered a "Run" button instead of polling.
_running: set[str] = set()
_running_lock = threading.Lock()


def _client():
    return current_app.extensions["multi_agent"]


def _get_assessment(assessment_id: int) -> Assessment:
    assessment = db.session.get(Assessment, assessment_id)
    if assessment is None:
        abort(404)
    return assessment


def _get_workflow(assessment_id: int, local_id: int) -> HealthWorkflow:
    assessment = _get_assessment(assessment_id)
    workflow = db.session.get(HealthWorkflow, local_id)
    if workflow is None or workflow.assessment_id != assessment.id:
        abort(404)
    return workflow


# --------------------------------------------------------------------------- #
# Evidence: one assessment and its plant's history, as citable passages       #
# --------------------------------------------------------------------------- #


def _label(text: str | None) -> str:
    # Titles become "<title>:" paragraph labels the Reviewer matches on.
    return " ".join((text or "").replace("—", "-").replace(":", " ").split())


def _clip(text: str) -> str:
    return text if len(text) <= MAX_PASSAGE_CHARS else text[: MAX_PASSAGE_CHARS - 1] + "…"


def _field(value) -> str:
    return str(value) if value not in (None, "", []) else "not recorded"


def assessment_evidence(assessment: Assessment) -> dict:
    """This assessment, and the same plant's earlier ones, as passages for the
    Worker and Reviewer. Every field is labelled and gaps are stated, so neither
    agent has to infer which value belongs to what."""

    name = _label(assessment.plant_ref or assessment.plant_identification) or "Plant"
    title = f"{name} assessment {assessment.id}"

    def passage(part: str, label: str, lines: list[str]) -> dict:
        return {
            "chunk_id": f"health-{assessment.id}-{part}",
            "title": f"{title} {label} — Plant Health record",
            "text": _clip("\n".join(lines)),
        }

    recorded = assessment.created_at.strftime("%Y-%m-%d") if assessment.created_at else "not recorded"
    summary = [
        f"Plant: {_field(assessment.plant_ref)}",
        f"Recorded: {recorded}",
        f"Status: {_field(assessment.status)}",
        f"Health score: {_field(assessment.health_score)} (0-100)"
        + (f", band {assessment.score_band}" if assessment.score_band else ""),
        f"Confidence: {_field(assessment.confidence_level)}"
        + (f" - {assessment.confidence_reason}" if assessment.confidence_reason else ""),
        f"Plant identified as: {_field(assessment.plant_identification)}",
        f"Photo supplied: {'yes' if assessment.has_image else 'no'}",
        f"Owner's description: {_field(assessment.description)}",
        f"Summary: {_field(assessment.summary)}",
        "Note: this is an earlier AI assessment with the stated confidence, not a diagnosis.",
    ]
    passages = [passage("assessment", "summary", summary)]

    issues = [
        f"{_field(i.get('name'))} - severity {_field(i.get('severity'))}; evidence {_field(i.get('evidence'))}"
        for i in assessment.issues
    ]
    passages.append(passage("issues", "issues", issues or ["No issues were recorded."]))

    recommendations = [
        f"{_field(r.get('action'))} - priority {_field(r.get('priority'))}; details {_field(r.get('details'))}"
        for r in assessment.recommendations
    ]
    missing = [f"Missing information: {m}" for m in assessment.missing_information]
    passages.append(passage(
        "recommendations", "recommendations and gaps",
        (recommendations or ["No recommendations were recorded."]) + missing,
    ))

    if assessment.plant_ref:
        earlier = (
            Assessment.query.filter(
                func.lower(Assessment.plant_ref) == assessment.plant_ref.lower(),
                Assessment.id != assessment.id,
            )
            .order_by(Assessment.created_at.desc(), Assessment.id.desc())
            .limit(HISTORY_LIMIT)
            .all()
        )
        if earlier:
            passages.append(passage("history", "earlier assessments of the same plant", [
                f"Assessment {e.id} on {e.created_at.strftime('%Y-%m-%d') if e.created_at else 'not recorded'}: "
                f"status {_field(e.status)}; health score {_field(e.health_score)}; summary {_field(e.summary)}"
                for e in earlier
            ]))
    return {"mode": "health-api", "passages": passages}


# --------------------------------------------------------------------------- #
# Running off the request thread                                              #
# --------------------------------------------------------------------------- #


def _run_in_background(client, workflow_id: str) -> None:
    def go():
        try:
            client.run(workflow_id)
        except (ValueError, WorkflowConflict, IntegrationDisabled, IntegrationUnavailable) as exc:
            # The server records stage failures itself; the page shows them on its next poll.
            logger.warning("Multi-agent workflow %s did not complete: %s", workflow_id, exc)
        finally:
            with _running_lock:
                _running.discard(workflow_id)

    with _running_lock:
        if workflow_id in _running:
            return
        _running.add(workflow_id)
    # Tests swap in a synchronous runner; production uses a daemon thread.
    runner = current_app.extensions.get("multi_agent_runner")
    if runner is not None:
        runner(go)
    else:
        threading.Thread(target=go, name=f"workflow-{workflow_id[:8]}", daemon=True).start()


def _render(assessment, workflow: HealthWorkflow, *, state: dict | None = None, error=None, code=200):
    """The workflow panel, or JSON. Refreshes the cached status from the server."""

    if state is None:
        try:
            state = _client().status(workflow.workflow_id)
        except (IntegrationDisabled, IntegrationUnavailable) as exc:
            if error is None:
                error, code = str(exc), 503 if isinstance(exc, IntegrationDisabled) else 502
    if state is not None and state.get("status") and state["status"] != workflow.status:
        workflow.status = state["status"]
        db.session.commit()
    with _running_lock:
        running = workflow.workflow_id in _running
    status = (state or {}).get("status", workflow.status)
    polling = status in IN_PROGRESS or (status in ("received", "changes_requested") and running)

    if not _wants_html():
        if error:
            return jsonify({"error": error, "status_code": code}), code
        return jsonify({"id": workflow.id, "assessment_id": assessment.id, "polling": polling,
                        **(state or {})}), code
    return render_template(
        "_workflow.html",
        assessment=assessment,
        workflow=workflow,
        state=state or {},
        status=status,
        polling=polling,
        error=error,
        final=status in FINAL,
    ), code


def _input():
    return (request.get_json(silent=True) or {}) if request.is_json else request.form


# --------------------------------------------------------------------------- #
# Routes                                                                      #
# --------------------------------------------------------------------------- #


@bp.route("/assessments/<int:assessment_id>/workflows", methods=["POST"])
def start_workflow(assessment_id):
    """Send a task plus this assessment's records to the Multi-Agent Server and start it."""

    assessment = _get_assessment(assessment_id)
    try:
        task = (_input().get("task") or "").strip()
        if not task:
            raise ValueError("Describe the task for the agents.")
        if len(task) > MAX_TASK_CHARS:
            raise ValueError(f"task must be {MAX_TASK_CHARS} characters or fewer.")
        created = _client().create(task, assessment_evidence(assessment))
    except (ValueError, IntegrationDisabled, IntegrationUnavailable) as exc:
        return _integration_error(exc, _wants_html())

    workflow = HealthWorkflow(
        assessment_id=assessment.id, workflow_id=created["workflow_id"], task=task, status="received"
    )
    db.session.add(workflow)
    db.session.commit()
    _run_in_background(_client(), workflow.workflow_id)
    return _render(assessment, workflow, code=201)


@bp.route("/assessments/<int:assessment_id>/workflows/<int:local_id>")
def workflow_detail(assessment_id, local_id):
    """Current plan, worker answer, AI review, human decision and history."""

    workflow = _get_workflow(assessment_id, local_id)
    return _render(workflow.assessment, workflow)


@bp.route("/assessments/<int:assessment_id>/workflows/<int:local_id>/run", methods=["POST"])
def rerun_workflow(assessment_id, local_id):
    """Run again after a failure or requested changes (feedback feeds the new plan)."""

    workflow = _get_workflow(assessment_id, local_id)
    _run_in_background(_client(), workflow.workflow_id)
    return _render(workflow.assessment, workflow, code=202)


@bp.route("/assessments/<int:assessment_id>/workflows/<int:local_id>/review", methods=["POST"])
def review_workflow(assessment_id, local_id):
    """Record the human decision. Requested changes start a revised run."""

    workflow = _get_workflow(assessment_id, local_id)
    source = _input()
    decision = (source.get("decision") or "").strip()
    feedback = (source.get("feedback") or "").strip()
    try:
        if decision not in DECISIONS:
            raise ValueError("Choose accept, partially accept, request changes or reject.")
        if len(feedback) > MAX_FEEDBACK_CHARS:
            raise ValueError(f"feedback must be {MAX_FEEDBACK_CHARS} characters or fewer.")
        reviewer_id = UI_REVIEWER_ID
        if request.is_json and source.get("reviewer_id") is not None:
            reviewer_id = str(source.get("reviewer_id"))
            if not REVIEWER_ID_CHARS.match(reviewer_id):
                raise ValueError("reviewer_id must be 1-100 letters, digits, '.', '_' or '-'.")
        state = _client().review(workflow.workflow_id, decision, feedback, reviewer_id)
    except WorkflowConflict as exc:
        return _render(workflow.assessment, workflow, error=str(exc), code=409)
    except (ValueError, IntegrationDisabled, IntegrationUnavailable) as exc:
        if _wants_html() and isinstance(exc, ValueError):
            return _render(workflow.assessment, workflow, error=str(exc), code=400)
        return _integration_error(exc, _wants_html())

    if state.get("status") == "changes_requested":
        _run_in_background(_client(), workflow.workflow_id)
        return _render(workflow.assessment, workflow)
    return _render(workflow.assessment, workflow, state=state)

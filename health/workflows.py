"""Plant Health UI access to the shared local Multi-Agent Server (Release 2).

Frontend UI -> this backend -> Multi-Agent Server -> Planner -> Worker -> Reviewer
-> Human Review (the gardener, on the records page) -> result shown here.

The boundaries match the Release 1 integration in routes.py:

- The browser never talks to the shared server. It only ever names a *local*
  ``HealthWorkflow`` row; the server's workflow id is looked up from that row and
  never taken from client input.
- The evidence sent with a task is this service's own stored assessments for one
  plant (or the latest records when no plant is named), read through the shared MCP
  server's Plant Health tools when MCP is on, else straight from the database. The
  shared server never reads health data itself.
- Assessments are the output of past local model runs, so every passage says so and
  the Worker is told to report what was recorded rather than diagnose.

A run makes three local model calls, which can outlast the proxy's timeout, so it
is started off the request thread and the page polls the workflow's status.
"""

from __future__ import annotations

import logging
import re
import threading

from flask import Blueprint, abort, current_app, jsonify, render_template, request

from extensions import db
from integrations import IntegrationDisabled, IntegrationUnavailable, WorkflowConflict
from models import Assessment, HealthWorkflow, Plant
from routes import MAX_PLANT_REF_CHARS, URL_PREFIX, _clean, _error, _integration_error, _wants_html
from sqlalchemy import func

logger = logging.getLogger(__name__)

bp = Blueprint("health_workflows", __name__, url_prefix=URL_PREFIX)

HISTORY_LIMIT = 5
UI_REVIEWER_ID = "health-user-web"
REVIEWER_ID_CHARS = re.compile(r"^[A-Za-z0-9._-]{1,100}$")

MAX_TASK_CHARS = 500
MAX_FEEDBACK_CHARS = 2000
MAX_REVIEWER_CHARS = 80
MAX_PASSAGE_CHARS = 4000
# The server accepts at most 10 passages: one history summary plus up to this many records.
EVIDENCE_RECORDS = 8
DEFAULT_REVIEWER = "health-ui"
DECISIONS = ("accept", "partially_accept", "request_changes", "reject")
IN_PROGRESS = ("planning", "working", "reviewing")
RUNNABLE = ("received", "changes_requested", "failed")
FINAL = ("accepted", "partially_accepted", "rejected")
STATUS_LABELS = {"healthy": "healthy", "at_risk": "at risk", "unhealthy": "unhealthy", "unknown": "unknown"}

# Workflow ids this process is currently running. A runnable workflow that is not
# here (e.g. the service restarted mid-run) is offered a "Run" button instead of polling.
_running: set[str] = set()
_running_lock = threading.Lock()


def _client():
    return current_app.extensions["multi_agent"]


def _get_workflow(local_id: int) -> HealthWorkflow:
    workflow = db.session.get(HealthWorkflow, local_id)
    if workflow is None or workflow.assessment_id is not None:
        abort(404)
    return workflow


# --------------------------------------------------------------------------- #
# Evidence: this plant's stored assessments, as citable passages               #
# --------------------------------------------------------------------------- #


def _label(text) -> str:
    # Titles become "<title>:" paragraph labels the Reviewer matches on, so they must
    # not contain the separators it splits on.
    return " ".join(str(text or "").replace("—", "-").replace(":", " ").split())


def _clip(text: str) -> str:
    return text if len(text) <= MAX_PASSAGE_CHARS else text[: MAX_PASSAGE_CHARS - 1] + "…"


def _field(value) -> str:
    return str(value) if value not in (None, "", []) else "not recorded"


def _records_from_db(plant_ref: str | None, limit: int) -> list[dict]:
    query = Assessment.query
    if plant_ref:
        query = query.filter(func.lower(Assessment.plant_ref) == plant_ref.lower())
    records = query.order_by(Assessment.created_at.desc(), Assessment.id.desc()).limit(limit).all()
    return [r.to_dict() for r in records]


def _records_from_mcp(mcp, plant_ref: str | None, limit: int) -> list[dict] | None:
    """The same records read through the shared MCP server's Plant Health tools
    (the Release 1 integration), or None if that is not possible right now."""

    try:
        arguments = {"limit": limit}
        if plant_ref:
            arguments["plant_ref"] = plant_ref
        listed = mcp.call("list_health_assessments", arguments)
        if listed["is_error"] or not isinstance(listed["structured_content"], dict):
            return None
        records = []
        for item in listed["structured_content"].get("items") or []:
            one = mcp.call("get_health_assessment", {"assessment_id": item["id"]})
            if one["is_error"] or not isinstance(one["structured_content"], dict):
                return None
            records.append(one["structured_content"])
        return records
    except (IntegrationDisabled, IntegrationUnavailable, KeyError, TypeError):
        logger.info("MCP unavailable; using the local assessments as evidence")
        return None


def _record_passage(record: dict, plant_label: str) -> dict:
    status = STATUS_LABELS.get(record.get("status"), record.get("status") or "unknown")
    score = record.get("health_score")
    score_text = f"{score}/100" if score is not None else "not recorded"
    if record.get("score_band"):
        score_text += f" ({_label(record['score_band'])})"
    issues = "; ".join(
        f"{i.get('name')} ({i.get('severity') or 'severity not recorded'})"
        + (f" - {i['evidence']}" if i.get("evidence") else "")
        for i in record.get("issues") or []
    )
    recommendations = "; ".join(
        f"{r.get('action')} (priority {r.get('priority') or 'not recorded'})"
        + (f" - {r['details']}" if r.get("details") else "")
        for r in record.get("recommendations") or []
    )
    lines = [
        f"Plant: {_field(record.get('plant_ref'))}",
        f"Assessed: {(record.get('created_at') or '')[:10] or 'date not recorded'} by local model {_field(record.get('model'))}",
        f"Status: {status}; health score {score_text}",
        f"Confidence: {_field(record.get('confidence'))}"
        + (f" - {record['confidence_reason']}" if record.get("confidence_reason") else ""),
        f"Plant identification: {_field(record.get('plant_identification'))}",
        f"Summary: {_field(record.get('summary'))}",
        f"Issues: {issues or 'none recorded'}",
        f"Recommendations: {recommendations or 'none recorded'}",
        f"Missing information: {'; '.join(record.get('missing_information') or []) or 'none recorded'}",
        f"Gardener's description: {_field(record.get('description'))}",
        f"Photo: {'yes' if record.get('has_image') else 'no'}",
    ]
    return {
        "chunk_id": f"health-{record['id']}",
        "title": f"Assessment {record['id']} {plant_label} — Plant Health record",
        "text": _clip("\n".join(lines)),
    }


def assessment_evidence(plant_ref: str | None, *, limit: int = EVIDENCE_RECORDS) -> dict:
    """This plant's stored assessments as passages for the Worker and Reviewer.

    Read through the shared MCP server when it is enabled, else from this service's
    own database; both yield the same records. Always includes one history summary
    passage, so a plant with no records still sends evidence that says so.
    """

    mode, records = "health-api", None
    mcp = current_app.extensions["mcp"]
    if mcp.enabled:
        records = _records_from_mcp(mcp, plant_ref, limit)
        if records is not None:
            mode = "mcp:get_health_assessment"
    if records is None:
        records = _records_from_db(plant_ref, limit)

    plant_label = _label(plant_ref) or "all plants"
    counts: dict[str, int] = {}
    for record in records:
        counts[record.get("status") or "unknown"] = counts.get(record.get("status") or "unknown", 0) + 1
    summary = [
        f"Plant: {plant_ref or 'no plant named; the latest assessments of any plant'}",
        f"Assessments recorded: {len(records)}"
        + (" (newest first: " + ", ".join(
            f"Assessment {r['id']} {STATUS_LABELS.get(r.get('status'), 'unknown')} {_field(r.get('health_score'))}"
            for r in records) + ")" if records else ""),
        "Status counts: " + (", ".join(f"{STATUS_LABELS.get(s, s)} {n}" for s, n in counts.items()) or "none"),
        "Note: each assessment is the advisory output of a past local model run, not a "
        "diagnosis. No record means nothing was assessed; it says nothing about the plant.",
    ]
    passages = [
        {
            "chunk_id": "health-history",
            "title": f"{plant_label} history — Plant Health record",
            "text": _clip("\n".join(summary)),
        }
    ]
    passages.extend(_record_passage(record, plant_label) for record in records)
    return {"mode": mode, "passages": passages}


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
        threading.Thread(target=go, name=f"health-workflow-{workflow_id[:8]}", daemon=True).start()


def _render(workflow: HealthWorkflow, *, state: dict | None = None, error=None, code=200):
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
        return jsonify({"id": workflow.id, "plant_ref": workflow.plant_ref, "polling": polling, **(state or {})}), code
    return render_template(
        "_workflow.html",
        workflow=workflow,
        state=state or {},
        status=status,
        polling=polling,
        error=error,
        final=status in FINAL,
    ), code


# --------------------------------------------------------------------------- #
# Routes                                                                      #
# --------------------------------------------------------------------------- #


@bp.route("/workflows", methods=["GET"])
def list_workflows():
    """Recent workflows started from this service (local rows; the server holds the rest)."""

    recent = HealthWorkflow.query.filter_by(assessment_id=None).order_by(
        HealthWorkflow.created_at.desc(), HealthWorkflow.id.desc()).limit(20).all()
    return jsonify([w.to_dict() for w in recent])


@bp.route("/workflows", methods=["POST"])
def start_workflow():
    """Send a task plus this plant's stored assessments to the Multi-Agent Server and start it."""

    wants_html = _wants_html()
    source = request.get_json(silent=True) or {} if request.is_json else request.form
    try:
        task = _clean(source.get("task"), MAX_TASK_CHARS, "task")
        if not task:
            raise ValueError("Describe the task for the agents.")
        plant_ref = _clean(source.get("plant_ref"), MAX_PLANT_REF_CHARS, "plant_ref")
        created = _client().create(task, assessment_evidence(plant_ref))
    except (ValueError, IntegrationDisabled, IntegrationUnavailable) as exc:
        return _integration_error(exc, wants_html)

    workflow = HealthWorkflow(
        workflow_id=created["workflow_id"], plant_ref=plant_ref, task=task, status="received"
    )
    db.session.add(workflow)
    db.session.commit()
    _run_in_background(_client(), workflow.workflow_id)
    return _render(workflow, code=201)


@bp.route("/workflows/<int:local_id>")
def workflow_detail(local_id):
    """Current plan, worker answer, AI review, human decision and history."""

    return _render(_get_workflow(local_id))


@bp.route("/workflows/<int:local_id>/run", methods=["POST"])
def rerun_workflow(local_id):
    """Run again after a failure or requested changes (feedback feeds the new plan)."""

    workflow = _get_workflow(local_id)
    _run_in_background(_client(), workflow.workflow_id)
    return _render(workflow, code=202)


@bp.route("/workflows/<int:local_id>/review", methods=["POST"])
def review_workflow(local_id):
    """Record the gardener's decision. Requested changes start a revised run."""

    workflow = _get_workflow(local_id)
    wants_html = _wants_html()
    source = request.get_json(silent=True) or {} if request.is_json else request.form
    decision = (source.get("decision") or "").strip()
    feedback = (source.get("feedback") or "").strip()
    try:
        if decision not in DECISIONS:
            raise ValueError("Choose accept, partially accept, request changes or reject.")
        if len(feedback) > MAX_FEEDBACK_CHARS:
            raise ValueError(f"feedback must be {MAX_FEEDBACK_CHARS} characters or fewer.")
        reviewer = _clean(source.get("reviewer"), MAX_REVIEWER_CHARS, "reviewer") or DEFAULT_REVIEWER
        state = _client().review(workflow.workflow_id, decision, feedback, reviewer)
    except WorkflowConflict as exc:
        return _render(workflow, error=str(exc), code=409)
    except ValueError as exc:
        if wants_html:
            return _render(workflow, error=str(exc), code=400)
        return _error(str(exc), 400, wants_html)
    except (IntegrationDisabled, IntegrationUnavailable) as exc:
        return _integration_error(exc, wants_html)

    if state.get("status") == "changes_requested":
        _run_in_background(_client(), workflow.workflow_id)
        return _render(workflow)
    return _render(workflow, state=state)


def recent_workflows(limit: int = 8) -> list[HealthWorkflow]:
    """For the records page panel."""

    return HealthWorkflow.query.filter_by(assessment_id=None).order_by(
        HealthWorkflow.created_at.desc(), HealthWorkflow.id.desc()).limit(limit).all()


def plant_choices() -> list[Plant]:
    return Plant.ordered()


# Assessment-scoped workflows complement the existing records-page workflows.


def _get_assessment(assessment_id: int) -> Assessment:
    assessment = db.session.get(Assessment, assessment_id)
    if assessment is None:
        abort(404)
    return assessment


def _get_assessment_workflow(assessment_id: int, local_id: int) -> HealthWorkflow:
    assessment = _get_assessment(assessment_id)
    workflow = db.session.get(HealthWorkflow, local_id)
    if workflow is None or workflow.assessment_id != assessment.id:
        abort(404)
    return workflow


def assessment_record_evidence(assessment: Assessment) -> dict:
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
                db.or_(Assessment.created_at < assessment.created_at,
                       db.and_(Assessment.created_at == assessment.created_at, Assessment.id < assessment.id)),
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


def _render_assessment(assessment, workflow: HealthWorkflow, *, state: dict | None = None, error=None, code=200):
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
        "_assessment_workflow.html",
        assessment=assessment,
        workflow=workflow,
        state=state or {},
        status=status,
        polling=polling,
        error=error,
        final=status in FINAL,
    ), code


def _assessment_input():
    data = (request.get_json(silent=True) or {}) if request.is_json else request.form
    if not hasattr(data, "get"):
        raise ValueError("Send a JSON object or form data.")
    return data


@bp.route("/assessments/<int:assessment_id>/workflows", methods=["POST"])
def start_assessment_workflow(assessment_id):
    """Send a task plus this assessment's records to the Multi-Agent Server and start it."""

    assessment = _get_assessment(assessment_id)
    try:
        task = _clean(_assessment_input().get("task"), MAX_TASK_CHARS, "task")
        if not task:
            raise ValueError("Describe the task for the agents.")
        if len(task) > MAX_TASK_CHARS:
            raise ValueError(f"task must be {MAX_TASK_CHARS} characters or fewer.")
        created = _client().create(task, assessment_record_evidence(assessment))
    except (ValueError, IntegrationDisabled, IntegrationUnavailable) as exc:
        return _integration_error(exc, _wants_html())

    workflow = HealthWorkflow(
        assessment_id=assessment.id, plant_ref=assessment.plant_ref,
        workflow_id=created["workflow_id"], task=task, status="received"
    )
    db.session.add(workflow)
    db.session.commit()
    _run_in_background(_client(), workflow.workflow_id)
    return _render_assessment(assessment, workflow, code=201)


@bp.route("/assessments/<int:assessment_id>/workflows/<int:local_id>")
def assessment_workflow_detail(assessment_id, local_id):
    """Current plan, worker answer, AI review, human decision and history."""

    workflow = _get_assessment_workflow(assessment_id, local_id)
    return _render_assessment(workflow.assessment, workflow)


@bp.route("/assessments/<int:assessment_id>/workflows/<int:local_id>/run", methods=["POST"])
def rerun_assessment_workflow(assessment_id, local_id):
    """Run again after a failure or requested changes (feedback feeds the new plan)."""

    workflow = _get_assessment_workflow(assessment_id, local_id)
    _run_in_background(_client(), workflow.workflow_id)
    return _render_assessment(workflow.assessment, workflow, code=202)


@bp.route("/assessments/<int:assessment_id>/workflows/<int:local_id>/review", methods=["POST"])
def review_assessment_workflow(assessment_id, local_id):
    """Record the human decision. Requested changes start a revised run."""

    workflow = _get_assessment_workflow(assessment_id, local_id)
    try:
        source = _assessment_input()
        decision = _clean(source.get("decision"), 30, "decision")
        feedback = _clean(source.get("feedback"), MAX_FEEDBACK_CHARS, "feedback") or ""
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
        return _render_assessment(workflow.assessment, workflow, error=str(exc), code=409)
    except (ValueError, IntegrationDisabled, IntegrationUnavailable) as exc:
        if _wants_html() and isinstance(exc, ValueError):
            return _render_assessment(workflow.assessment, workflow, error=str(exc), code=400)
        return _integration_error(exc, _wants_html())

    if state.get("status") == "changes_requested":
        _run_in_background(_client(), workflow.workflow_id)
        return _render_assessment(workflow.assessment, workflow)
    return _render_assessment(workflow.assessment, workflow, state=state)

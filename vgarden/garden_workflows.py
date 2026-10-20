"""Virtual Garden UI access to the shared local Multi-Agent Server (Release 2).

Frontend UI -> this backend -> Multi-Agent Server -> Planner -> Worker -> Reviewer
-> Human Review (the garden's owner, on the garden page) -> result shown here.

Garden data is private per-owner, so the boundaries match garden_integrations.py:

- Every route is ``require_login`` + owner-scoped (404 for a stranger).
- The browser only ever names a *local* ``GardenWorkflow`` row under a garden it
  owns; the Multi-Agent Server's workflow id is looked up from that row, never
  taken from client input, so an owner can never review someone else's workflow.
- The evidence sent with a task is this one garden's records. The shared server
  never reads garden data itself.

A run makes three local model calls, which can outlast the proxy's timeout, so it
is started off the request thread and the page polls the workflow's status.
"""

from __future__ import annotations

import logging
import threading

from flask import Blueprint, abort, current_app, jsonify, render_template, request

from auth_utils import current_user_id, require_login
from extensions import db
from garden_integrations import _get_owned_garden, _integration_error, _wants_html
from integrations import IntegrationDisabled, IntegrationUnavailable, WorkflowConflict
from models import GardenWorkflow
from routes import _garden_snapshot_payload

logger = logging.getLogger(__name__)

bp = Blueprint("garden_workflows", __name__)

MAX_TASK_CHARS = 500
MAX_FEEDBACK_CHARS = 2000
MAX_PASSAGE_CHARS = 4000
DECISIONS = ("accept", "partially_accept", "request_changes", "reject")
IN_PROGRESS = ("planning", "working", "reviewing")
RUNNABLE = ("received", "changes_requested", "failed")
FINAL = ("accepted", "partially_accepted", "rejected")

# Workflow ids this process is currently running. A runnable workflow that is not
# here (e.g. vgarden restarted mid-run) is offered a "Run" button instead of polling.
_running: set[str] = set()
_running_lock = threading.Lock()


def _client():
    return current_app.extensions["multi_agent"]


def _get_garden_workflow(garden_id: int, local_id: int) -> GardenWorkflow:
    garden = _get_owned_garden(garden_id)
    workflow = db.session.get(GardenWorkflow, local_id)
    if workflow is None or workflow.garden_id != garden.id:
        abort(404)
    return workflow


# --------------------------------------------------------------------------- #
# Evidence: this garden's records, as citable passages                        #
# --------------------------------------------------------------------------- #


def _label(text: str) -> str:
    # Titles become "<title>:" paragraph labels the Reviewer matches on.
    return " ".join((text or "").replace("—", "-").replace(":", " ").split())


def _clip(text: str) -> str:
    return text if len(text) <= MAX_PASSAGE_CHARS else text[: MAX_PASSAGE_CHARS - 1] + "…"


def garden_evidence(garden) -> dict:
    """This garden's snapshot as passages for the Worker and Reviewer.

    The snapshot is read through the shared MCP server's ``get_garden_snapshot``
    tool when MCP is enabled (the Release 1 integration), else straight from this
    service's own snapshot endpoint logic. Both return the same payload.
    """

    mode = "vgarden-api"
    snapshot = None
    mcp = current_app.extensions["mcp"]
    if mcp.enabled:
        try:
            result = mcp.call("get_garden_snapshot", garden.id)
            if not result["is_error"] and isinstance(result["structured_content"], dict):
                snapshot, mode = result["structured_content"], "mcp:get_garden_snapshot"
        except (IntegrationDisabled, IntegrationUnavailable):
            logger.info("MCP unavailable; using the local garden snapshot as evidence")
    if snapshot is None:
        snapshot = _garden_snapshot_payload(garden)

    name = _label(snapshot.get("name")) or f"Garden {garden.id}"
    areas = snapshot.get("areas") or []
    containers = snapshot.get("containers") or []
    plantings = snapshot.get("plantings") or []

    def passage(part: str, label: str, lines: list[str]) -> dict:
        return {
            "chunk_id": f"garden-{garden.id}-{part}",
            "title": f"{name} {label} — Virtual Garden record",
            "text": _clip("\n".join(lines)),
        }

    summary = [f"Garden name: {snapshot.get('name')}"]
    if snapshot.get("location_label"):
        summary.append(f"Location: {snapshot['location_label']}")
    if snapshot.get("climate_zone"):
        summary.append(f"Climate zone: {snapshot['climate_zone']}")
    summary.append(
        f"Recorded: {len(areas)} area(s), {len(containers)} container(s), {len(plantings)} planting(s)"
    )
    if snapshot.get("evidence_note"):
        summary.append(f"Note: {snapshot['evidence_note']}")
    passages = [passage("summary", "summary", summary)]

    if areas:
        passages.append(passage("areas", "areas", [
            f"{a.get('name')} ({a.get('area_type') or 'area'}, {a.get('width')} x {a.get('length')} m)"
            + (f" - {a['notes']}" if a.get("notes") else "")
            for a in areas
        ]))
    if containers:
        passages.append(passage("containers", "containers", [
            f"{c.get('name')} ({c.get('container_type') or 'container'})" for c in containers
        ]))
    if plantings:
        # Every field labelled, and gaps stated, so neither agent has to infer which
        # value belongs to which planting.
        def field(value):
            return value if value not in (None, "") else "not recorded"

        passages.append(passage("plantings", "plantings", [
            f"{p.get('crop_name')} - quantity {field(p.get('quantity'))}; "
            f"status {field(p.get('lifecycle_state'))}; growth stage {field(p.get('growth_stage'))}; "
            f"location {field(p.get('location'))}; planted {field(p.get('planted_date'))}; "
            f"expected harvest {field(p.get('expected_harvest_date'))}"
            for p in plantings
        ]))
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
        threading.Thread(target=go, name=f"workflow-{workflow_id[:8]}", daemon=True).start()


def _render(garden, workflow: GardenWorkflow, *, state: dict | None = None, error=None, code=200):
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
        return jsonify({"id": workflow.id, "garden_id": garden.id, "polling": polling, **(state or {})}), code
    return render_template(
        "_workflow.html",
        garden=garden,
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


@bp.route("/gardens/<int:garden_id>/workflows", methods=["POST"])
@require_login
def start_workflow(garden_id):
    """Send a task plus this garden's records to the Multi-Agent Server and start it."""

    garden = _get_owned_garden(garden_id)
    source = request.get_json(silent=True) or {} if request.is_json else request.form
    try:
        task = (source.get("task") or "").strip()
        if not task:
            raise ValueError("Describe the task for the agents.")
        if len(task) > MAX_TASK_CHARS:
            raise ValueError(f"task must be {MAX_TASK_CHARS} characters or fewer.")
        created = _client().create(task, garden_evidence(garden))
    except (ValueError, IntegrationDisabled, IntegrationUnavailable) as exc:
        return _integration_error(exc, _wants_html())

    workflow = GardenWorkflow(
        garden_id=garden.id, workflow_id=created["workflow_id"], task=task, status="received"
    )
    db.session.add(workflow)
    db.session.commit()
    _run_in_background(_client(), workflow.workflow_id)
    return _render(garden, workflow, code=201)


@bp.route("/gardens/<int:garden_id>/workflows/<int:local_id>")
@require_login
def workflow_detail(garden_id, local_id):
    """Current plan, worker answer, AI review, human decision and history."""

    workflow = _get_garden_workflow(garden_id, local_id)
    return _render(workflow.garden, workflow)


@bp.route("/gardens/<int:garden_id>/workflows/<int:local_id>/run", methods=["POST"])
@require_login
def rerun_workflow(garden_id, local_id):
    """Run again after a failure or requested changes (feedback feeds the new plan)."""

    workflow = _get_garden_workflow(garden_id, local_id)
    _run_in_background(_client(), workflow.workflow_id)
    return _render(workflow.garden, workflow, code=202)


@bp.route("/gardens/<int:garden_id>/workflows/<int:local_id>/review", methods=["POST"])
@require_login
def review_workflow(garden_id, local_id):
    """Record the owner's decision. Requested changes start a revised run."""

    workflow = _get_garden_workflow(garden_id, local_id)
    source = request.get_json(silent=True) or {} if request.is_json else request.form
    decision = (source.get("decision") or "").strip()
    feedback = (source.get("feedback") or "").strip()
    try:
        if decision not in DECISIONS:
            raise ValueError("Choose accept, partially accept, request changes or reject.")
        if len(feedback) > MAX_FEEDBACK_CHARS:
            raise ValueError(f"feedback must be {MAX_FEEDBACK_CHARS} characters or fewer.")
        state = _client().review(
            workflow.workflow_id, decision, feedback, f"vgarden-user-{current_user_id()}"
        )
    except WorkflowConflict as exc:
        return _render(workflow.garden, workflow, error=str(exc), code=409)
    except (ValueError, IntegrationDisabled, IntegrationUnavailable) as exc:
        if _wants_html() and isinstance(exc, ValueError):
            return _render(workflow.garden, workflow, error=str(exc), code=400)
        return _integration_error(exc, _wants_html())

    if state.get("status") == "changes_requested":
        _run_in_background(_client(), workflow.workflow_id)
        return _render(workflow.garden, workflow)
    return _render(workflow.garden, workflow, state=state)

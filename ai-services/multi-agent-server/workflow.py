import logging

from planner import create_plan
from reviewer import review_result
from store import WorkflowConflict, get_workflow, transition
from worker import run_worker


def run_workflow(workflow_id):
    workflow = get_workflow(workflow_id)
    if workflow is None:
        raise LookupError("Workflow not found")
    if workflow["status"] not in ("received", "changes_requested", "failed"):
        raise WorkflowConflict("Workflow cannot run in its current state")
    feedback = workflow.get("human_review", {}).get("feedback", workflow.get("revision_feedback", ""))
    task = workflow["task"]
    # Keep feedback separate from the original task in the saved history.
    transition(workflow_id, workflow["status"], "planning", {"revision_feedback": feedback})
    stage = "planning"
    try:
        planning_task = task + (f"\nRequested changes: {feedback}" if feedback else "")
        plan = create_plan(planning_task)
        transition(workflow_id, stage, "working", {"plan": plan})
        stage = "working"
        output = run_worker(task, plan)
        transition(workflow_id, stage, "reviewing", output)
        stage = "reviewing"
        review = review_result(plan, output["result"], output["evidence"])
        transition(workflow_id, stage, "awaiting_human_review", {"review": review})
    except Exception:
        logging.exception("Workflow %s failed at %s", workflow_id, stage)
        transition(workflow_id, stage, "failed", {"error": f"{stage} failed"})
        raise RuntimeError(f"{stage} failed; check the server log") from None
    return get_workflow(workflow_id)

from store import WorkflowConflict, get_workflow, transition


def record_decision(
    workflow_id: str, decision: str, feedback: str, reviewer_id: str
) -> dict:
    if decision not in ("accept", "partially_accept", "request_changes", "reject"):
        raise ValueError("Use accept, partially_accept, request_changes or reject")
    if not isinstance(feedback, str) or len(feedback) > 2000:
        raise ValueError("feedback must be text, up to 2000 characters")
    if not isinstance(reviewer_id, str) or not 1 <= len(reviewer_id.strip()) <= 100:
        raise ValueError("reviewer_id is required, up to 100 characters")
    if decision == "request_changes" and not feedback.strip():
        raise ValueError("Explain the requested changes")
    if decision == "partially_accept" and not feedback.strip():
        raise ValueError("Explain what is approved and what remains unresolved")
    workflow = get_workflow(workflow_id)
    if workflow is None:
        raise LookupError("Workflow not found")
    if workflow["status"] != "awaiting_human_review":
        raise WorkflowConflict("Workflow is not awaiting human review")
    if (decision == "accept" and workflow["review"]["recommendation"] == "revise"
            and not feedback.strip()):
        raise ValueError("Explain why you accept despite the AI review issues")
    status = {"accept": "accepted", "partially_accept": "partially_accepted",
              "request_changes": "changes_requested",
              "reject": "rejected"}[decision]
    transition(workflow_id, "awaiting_human_review", status, {
        "human_review": {"decision": decision, "feedback": feedback.strip(),
                         "reviewer_id": reviewer_id.strip()},
    })
    return get_workflow(workflow_id)

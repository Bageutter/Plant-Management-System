"""HTTP boundary for the shared, locally running Multi-Agent Server."""

import httpx
from flask import current_app


def request_workflow(path, payload=None, workflow_id=None):
    url = current_app.config["MULTI_AGENT_SERVER_URL"].rstrip("/") + path
    with httpx.Client(timeout=httpx.Timeout(420, connect=5), follow_redirects=False) as client:
        response = (client.get(url, params={"id": workflow_id}) if workflow_id
                    else client.post(url, json=payload))
    response.raise_for_status()
    try:
        body = response.json()
    except ValueError as exc:
        raise RuntimeError("Invalid workflow response") from exc
    if (not isinstance(body, dict)
            or not isinstance(body.get("workflow_id"), str) or not body["workflow_id"].strip()
            or not isinstance(body.get("status"), str) or not body["status"].strip()):
        raise RuntimeError("Invalid workflow response")
    if "result" in body and (not isinstance(body["result"], dict)
                             or not isinstance(body["result"].get("answer"), str)):
        raise RuntimeError("Invalid workflow answer")
    return body


def review_view(workflow):
    """Present saved evidence as readable facts, without inventing model claims."""
    from urllib.parse import urlsplit

    outcome = workflow.get("result") or {}
    review = workflow.get("review") or {}
    cited = set(outcome.get("cited_chunk_ids") or [])
    passages = (workflow.get("evidence") or {}).get("passages") or []
    titles = {p.get("chunk_id"): p.get("title", "Saved reference").split("—")[0].strip()
              for p in passages if isinstance(p, dict)}
    sources = []
    fields = [("Sunlight", "Sun needs"), ("Water needs", "Water needs"),
              ("Minimum soil pH", "Minimum soil pH"), ("Maximum soil pH", "Maximum soil pH"),
              ("Care", "Care"), ("Feeding", "Feeder type")]
    for passage in passages:
        if not isinstance(passage, dict) or passage.get("chunk_id") not in cited:
            continue
        recorded = {}
        for line in passage.get("text", "").splitlines():
            key, sep, value = line.partition(":")
            if sep:
                recorded[key.strip()] = value.strip().rstrip(".")
        url = passage.get("url", "")
        if not isinstance(url, str) or urlsplit(url).scheme not in ("http", "https"):
            url = None
        sources.append({"title": titles.get(passage.get("chunk_id"), "Saved reference"),
                        "url": url, "text": passage.get("text", ""),
                        "facts": [{"label": label, "value": recorded.get(key) or "Not recorded"}
                                  for label, key in fields]})
    concerns = []
    for issue in review.get("issues") or []:
        if not isinstance(issue, str):
            continue
        if issue.startswith("Remove unused citation: "):
            name = titles.get(issue.removeprefix("Remove unused citation: "), "A cited reference")
            issue = (f"Source attribution needs checking for {name}. The reviewer could not match it "
                     "to a plant-labelled part of the draft; this does not prove the source is unused.")
        elif issue.startswith("Unknown citation: "):
            issue = "The answer cites a reference that was not returned. Request a source-backed correction."
        else:
            for key, title in titles.items():
                if key:
                    issue = issue.replace(key, title)
        concerns.append(issue)
    needs_changes = bool(concerns or review.get("recommendation") == "revise"
                         or outcome.get("insufficient_context") or (outcome and not sources))
    status_labels = {"received": "Ready to run", "planning": "Planning the answer",
                     "working": "Reading saved sources", "reviewing": "Checking the draft",
                     "awaiting_human_review": "Your review is needed", "accepted": "Answer accepted",
                     "partially_accepted": "Answer partly accepted", "changes_requested": "Changes requested",
                     "rejected": "Answer rejected", "failed": "The agents could not finish"}
    order = ("planning", "working", "reviewing", "awaiting_human_review")
    names = ("Planner", "Worker", "Reviewer", "Human review")
    current = workflow.get("status")
    visited = [event.get("status") for event in workflow.get("history", [])]
    starts = [i for i, phase in enumerate(visited) if phase == "planning"]
    if starts:
        visited = visited[starts[-1]:]
    final = current in ("accepted", "partially_accepted", "rejected", "changes_requested")
    stages = []
    for index, (phase, label) in enumerate(zip(order, names)):
        later = any(p in visited or p == current for p in order[index + 1:])
        state = ("current" if phase == current else "complete" if final or later
                 else "complete" if phase in visited and current != "failed" else "pending")
        stages.append({"label": label, "state": state})
    feedback = "Please revise the answer using each plant's own saved evidence."
    if concerns:
        feedback += "\n" + "\n".join("- " + issue for issue in concerns)
    return {"status": status_labels.get(workflow.get("status"), "Check workflow status"),
            "stages": stages,
            "concerns": concerns, "sources": sources, "needs_changes": needs_changes,
            "feedback": feedback[:2000], "default_decision": "request_changes" if needs_changes else ""}

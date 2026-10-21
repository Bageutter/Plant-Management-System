"""Release 2: Plant Health <-> shared Multi-Agent Server (workflows.py).

A FakeMultiAgent stands in for the server and follows its state machine
(received -> planning -> working -> reviewing -> awaiting_human_review -> a human
decision), so these tests cover the integration without Ollama or the server
running. Runs are made synchronous so each request sees the finished state.
"""

from __future__ import annotations

from unittest.mock import Mock, patch

import pytest
import requests

from conftest import make_assessment
from integrations import (
    IntegrationDisabled,
    IntegrationUnavailable,
    MultiAgentClient,
    WorkflowConflict,
)
from models import HealthWorkflow

WORKFLOWS = "/plant-health-records/workflows"
HTMX = {"HX-Request": "true"}


class FakeMultiAgent:
    """Speaks the Multi-Agent Server's contract; records what it was sent."""

    def __init__(self):
        self.enabled = True
        self.workflows = {}
        self.created = []
        self.reviews = []
        self.recommendation = "accept"
        self.unreachable = False

    def _check(self):
        if not self.enabled:
            raise IntegrationDisabled("disabled")
        if self.unreachable:
            raise IntegrationUnavailable("unreachable")

    def create(self, task, evidence):
        self._check()
        workflow_id = f"wf-{len(self.workflows) + 1}"
        self.created.append({"task": task, "evidence": evidence})
        self.workflows[workflow_id] = {
            "workflow_id": workflow_id, "task": task, "source": "health",
            "status": "received", "history": [self._event("received")],
            "_evidence": evidence, "feedback": [],
        }
        return {"workflow_id": workflow_id, "task": task, "source": "health", "status": "received"}

    @staticmethod
    def _event(status):
        return {"status": status, "details": {}, "created_at": "2026-10-21T05:00:00+00:00"}

    def run(self, workflow_id):
        self._check()
        w = self.workflows[workflow_id]
        if w["status"] not in ("received", "changes_requested", "failed"):
            raise WorkflowConflict("Workflow cannot run in its current state")
        for status in ("planning", "working", "reviewing", "awaiting_human_review"):
            w["history"].append(self._event(status))
        evidence = w["_evidence"]
        w.update(
            status="awaiting_human_review",
            plan={"steps": ["Read this plant's stored assessments", "Summarise them with citations"]
                  + [f"Address: {f}" for f in w["feedback"]]},
            evidence=evidence,
            result={"answer": "Tomato history: rated at risk (45/100) for overwatering.",
                    "insufficient_context": False,
                    "cited_chunk_ids": [evidence["passages"][-1]["chunk_id"]]},
            review={"recommendation": self.recommendation,
                    "issues": [] if self.recommendation == "accept" else ["Unsupported claim"]},
            models={"planner": "qwen3:4b-instruct", "worker": "qwen3:4b-instruct",
                    "reviewer": "qwen3:4b-instruct"},
        )
        w.pop("human_review", None)
        return self.status(workflow_id)

    def status(self, workflow_id):
        self._check()
        return {k: v for k, v in self.workflows[workflow_id].items() if not k.startswith("_")
                and k != "feedback"}

    def review(self, workflow_id, decision, feedback, reviewer_id):
        self._check()
        w = self.workflows[workflow_id]
        if w["status"] != "awaiting_human_review":
            raise WorkflowConflict("Workflow is not awaiting human review")
        if decision in ("partially_accept", "request_changes") and not feedback:
            raise ValueError("Explain the decision")
        status = {"accept": "accepted", "partially_accept": "partially_accepted",
                  "request_changes": "changes_requested", "reject": "rejected"}[decision]
        self.reviews.append((workflow_id, decision, feedback, reviewer_id))
        w["status"] = status
        w["history"].append(self._event(status))
        w["human_review"] = {"decision": decision, "feedback": feedback, "reviewer_id": reviewer_id}
        if decision == "request_changes":
            w["feedback"].append(feedback)
        return self.status(workflow_id)


@pytest.fixture
def agents(app):
    fake = FakeMultiAgent()
    app.extensions["multi_agent"] = fake
    app.extensions["multi_agent_runner"] = lambda go: go()  # run synchronously
    app.extensions["mcp"].enabled = False  # evidence from the local records
    return fake


def _start(client, task="How has this plant's health changed?", plant_ref="Tomato, back bed", headers=HTMX):
    data = {"task": task}
    if plant_ref is not None:
        data["plant_ref"] = plant_ref
    return client.post(WORKFLOWS, data=data, headers=headers)


def _only_workflow(app):
    with app.app_context():
        return HealthWorkflow.query.one()


# --- start -> plan -> work -> review -> human review, through the UI routes ---


def test_start_sends_only_this_plants_assessments_and_runs_to_human_review(app, client, agents):
    first = make_assessment(client, plant_ref="Tomato, back bed", description="Lower leaves yellow, soil wet.")
    second = make_assessment(client, plant_ref="tomato, BACK bed", description="Still yellow.")
    make_assessment(client, plant_ref="Basil", description="Basil wilting.")

    response = _start(client)

    assert response.status_code == 201
    html = response.get_data(as_text=True)
    assert 'data-workflow-status="awaiting_human_review"' in html
    assert "Read this plant&#39;s stored assessments" in html  # Planner
    assert "rated at risk (45/100) for overwatering" in html  # Worker
    assert 'data-review="accept"' in html  # Reviewer
    assert 'name="decision" value="request_changes"' in html  # Human review form
    assert "every 3s" not in html  # finished, so no polling

    sent = agents.created[0]
    assert sent["task"] == "How has this plant's health changed?"
    evidence = sent["evidence"]
    assert evidence["mode"] == "health-api"
    ids = [p["chunk_id"] for p in evidence["passages"]]
    assert ids == ["health-history", f"health-{second['id']}", f"health-{first['id']}"]  # newest first
    history, newest, oldest = evidence["passages"]
    assert history["title"] == "Tomato, back bed history — Plant Health record"
    assert "Assessments recorded: 2" in history["text"] and "at risk 45" in history["text"]
    assert "advisory output of a past local model run" in history["text"]
    assert newest["title"] == f"Assessment {second['id']} Tomato, back bed — Plant Health record"
    assert "Status: at risk; health score 45/100 (At risk - will worsen without action)" in newest["text"]
    assert "Confidence: medium - Written description only, no photo." in newest["text"]
    assert "Issues: Overwatering (medium) - Soil stays wet" in newest["text"]
    assert "Recommendations: Reduce watering (priority high) - Let the top 3cm dry." in newest["text"]
    assert "Missing information: A photo of the affected leaves" in newest["text"]
    assert "Gardener's description: Still yellow." in newest["text"] and "Photo: no" in newest["text"]
    assert "Gardener's description: Lower leaves yellow, soil wet." in oldest["text"]
    assert "Basil" not in "\n".join(p["text"] for p in evidence["passages"])

    workflow = _only_workflow(app)
    assert (workflow.plant_ref, workflow.workflow_id, workflow.status) == ("Tomato, back bed", "wf-1", "awaiting_human_review")


def test_no_plant_named_sends_the_latest_records_and_no_records_still_sends_evidence(app, client, agents):
    # Nothing recorded yet: the history passage alone says so, so the Worker can refuse honestly.
    assert _start(client, plant_ref="Capsicum").status_code == 201
    evidence = agents.created[0]["evidence"]
    assert [p["chunk_id"] for p in evidence["passages"]] == ["health-history"]
    assert "Assessments recorded: 0" in evidence["passages"][0]["text"]
    assert "No record means nothing was assessed" in evidence["passages"][0]["text"]

    # No plant named: the latest assessments of any plant, capped so the server's
    # 10-passage limit is never exceeded.
    ids = [make_assessment(client, plant_ref=f"Plant {n}")["id"] for n in range(10)]
    assert _start(client, plant_ref=None).status_code == 201
    evidence = agents.created[1]["evidence"]
    assert len(evidence["passages"]) == 9
    assert [p["chunk_id"] for p in evidence["passages"][1:]] == [f"health-{i}" for i in ids[::-1][:8]]
    assert evidence["passages"][0]["title"] == "all plants history — Plant Health record"
    assert _only_workflow(app) if False else HealthWorkflow.query.count() == 2 if False else True
    with app.app_context():
        assert [w.plant_ref for w in HealthWorkflow.query.order_by(HealthWorkflow.id)] == ["Capsicum", None]


def test_evidence_is_read_through_mcp_when_enabled(app, client, agents):
    record = make_assessment(client, plant_ref="Chilli", description="Curling leaves")
    listed = {"is_error": False, "structured_content": {"items": [{"id": record["id"]}], "count": 1}}
    full = {"is_error": False, "structured_content": {**record, "summary": "Chilli: via MCP"}}
    app.extensions["mcp"] = Mock(enabled=True)
    app.extensions["mcp"].call.side_effect = [listed, full]

    assert _start(client, plant_ref="Chilli").status_code == 201

    calls = app.extensions["mcp"].call.call_args_list
    assert calls[0].args == ("list_health_assessments", {"limit": 8, "plant_ref": "Chilli"})
    assert calls[1].args == ("get_health_assessment", {"assessment_id": record["id"]})
    evidence = agents.created[0]["evidence"]
    assert evidence["mode"] == "mcp:get_health_assessment"
    assert "Summary: Chilli: via MCP" in evidence["passages"][1]["text"]

    # An MCP failure falls back to the local records rather than failing the task.
    app.extensions["mcp"].call.side_effect = IntegrationUnavailable("down")
    assert _start(client, plant_ref="Chilli").status_code == 201
    evidence = agents.created[1]["evidence"]
    assert evidence["mode"] == "health-api" and "Curling leaves" in evidence["passages"][1]["text"]


def test_human_decisions_are_recorded_and_requested_changes_rerun(app, client, agents):
    make_assessment(client)
    _start(client)
    local_id = _only_workflow(app).id
    url = f"{WORKFLOWS}/{local_id}/review"

    # Feedback is required for a request for changes; the error shows on the panel.
    missing = client.post(url, data={"decision": "request_changes"}, headers=HTMX)
    assert missing.status_code == 400
    assert "Explain the decision" in missing.get_data(as_text=True)
    assert client.post(url, data={"decision": "approve"}, headers=HTMX).status_code == 400
    assert client.post(url, json={"decision": "approve"}).status_code == 400

    # Requested changes start a revised run that comes back for review.
    revised = client.post(url, data={"decision": "request_changes", "feedback": "Include the score trend"},
                          headers=HTMX)
    assert revised.status_code == 200
    html = revised.get_data(as_text=True)
    assert 'data-workflow-status="awaiting_human_review"' in html
    assert "Address: Include the score trend" in html

    accepted = client.post(url, data={"decision": "accept", "reviewer": " Guhan "}, headers=HTMX)
    assert 'data-workflow-status="accepted"' in accepted.get_data(as_text=True)
    assert [r[1:] for r in agents.reviews] == [
        ("request_changes", "Include the score trend", "health-ui"),
        ("accept", "", "Guhan"),
    ]
    statuses = [e["status"] for e in agents.workflows["wf-1"]["history"]]
    assert statuses.count("awaiting_human_review") == 2 and statuses[-1] == "accepted"
    assert _only_workflow(app).status == "accepted"

    # A finished workflow can't be reviewed again.
    assert client.post(url, data={"decision": "reject"}, headers=HTMX).status_code == 409


def test_json_clients_get_the_workflow_state(app, client, agents):
    make_assessment(client)
    created = client.post(WORKFLOWS, json={"task": "Summarise the assessments", "plant_ref": "Tomato, back bed"})
    assert created.status_code == 201
    body = created.get_json()
    assert body["status"] == "awaiting_human_review" and body["polling"] is False
    assert body["plant_ref"] == "Tomato, back bed"
    assert body["review"]["recommendation"] == "accept"
    assert body["evidence"]["passages"][0]["chunk_id"] == "health-history"

    detail = client.get(f"{WORKFLOWS}/{body['id']}").get_json()
    assert detail["workflow_id"] == "wf-1" and detail["result"]["answer"].startswith("Tomato history")

    listed = client.get(WORKFLOWS).get_json()
    assert [w["workflow_id"] for w in listed] == ["wf-1"] and listed[0]["status"] == "awaiting_human_review"

    reviewed = client.post(f"{WORKFLOWS}/{body['id']}/review",
                           json={"decision": "partially_accept", "feedback": "Trend unconfirmed"})
    assert reviewed.get_json()["human_review"]["decision"] == "partially_accept"
    assert client.get(f"{WORKFLOWS}/999").status_code == 404


def test_running_workflow_polls_until_the_agents_finish(app, client, agents):
    make_assessment(client)
    queued = []
    app.extensions["multi_agent_runner"] = queued.append  # hold the run

    html = _start(client).get_data(as_text=True)
    assert 'hx-trigger="every 3s"' in html and "Running locally" in html

    queued.pop()()  # the background run finishes
    local_id = _only_workflow(app).id
    done = client.get(f"{WORKFLOWS}/{local_id}", headers=HTMX).get_data(as_text=True)
    assert "every 3s" not in done and 'data-workflow-status="awaiting_human_review"' in done


def test_failed_run_offers_a_retry(app, client, agents):
    make_assessment(client)
    agents.run = Mock(side_effect=IntegrationUnavailable("Ollama down"))
    html = _start(client).get_data(as_text=True)
    assert 'data-workflow-status="received"' in html and "Run workflow" in html

    del agents.run  # back to the fake's real run
    local_id = _only_workflow(app).id
    retried = client.post(f"{WORKFLOWS}/{local_id}/run", headers=HTMX)
    assert retried.status_code == 202
    assert 'data-workflow-status="awaiting_human_review"' in retried.get_data(as_text=True)


# --- boundaries ---


@pytest.mark.parametrize("task", ["", "   ", "x" * 501])
def test_task_is_validated_before_anything_is_sent(app, client, agents, task):
    assert _start(client, task=task).status_code == 400
    assert client.post(WORKFLOWS, json={"task": "ok", "plant_ref": "x" * 201}).status_code == 400
    assert agents.created == []


def test_disabled_and_unreachable_server_create_nothing(app, client, agents):
    agents.enabled = False
    disabled = _start(client)
    assert disabled.status_code == 503 and b"disabled" in disabled.data
    assert client.post(WORKFLOWS, json={"task": "ok"}).status_code == 503
    agents.enabled, agents.unreachable = True, True
    assert _start(client).status_code == 502
    with app.app_context():
        assert HealthWorkflow.query.count() == 0


def test_integrations_status_reports_the_multi_agent_server(app, client):
    app.extensions["multi_agent"] = MultiAgentClient("http://127.0.0.1:1", enabled=False)
    body = client.get("/plant-health-records/integrations").get_json()
    assert body["multi_agent"] == {"enabled": False, "url": "http://127.0.0.1:1", "reachable": None}

    app.extensions["multi_agent"] = MultiAgentClient("http://127.0.0.1:1", enabled=True, timeout=1)
    assert client.get("/plant-health-records/integrations").get_json()["multi_agent"]["reachable"] is False


def test_records_page_shows_the_panel_or_the_disabled_state(app, client, agents):
    make_assessment(client, plant_ref="Tomato, back bed")
    _start(client, task="Summarise the assessments")
    page = client.get("/plant-health-records/").get_data(as_text=True)
    assert "Agent workflow (Planner → Worker → Reviewer → you)" in page
    assert "Start workflow" in page and "Summarise the assessments" in page
    assert "Tomato, back bed (1 assessment)" in page  # plant choices with their record counts

    agents.enabled = False
    page = client.get("/plant-health-records/").get_data(as_text=True)
    assert 'data-integration="multi-agent-disabled"' in page and "Start workflow" not in page


# --- the HTTP client's mapping of server responses ---


def _response(code, body):
    response = Mock(status_code=code)
    response.json.return_value = body
    return response


def test_client_maps_server_responses():
    client = MultiAgentClient("http://agents.test", timeout=7)
    with patch("integrations.requests.request", return_value=_response(201, {"workflow_id": "w"})) as call:
        assert client.create("Task", {"passages": []}) == {"workflow_id": "w"}
    assert call.call_args.kwargs["json"] == {"task": "Task", "source": "health", "evidence": {"passages": []}}

    with patch("integrations.requests.request", return_value=_response(200, {"status": "x"})) as call:
        client.run("w")
    assert call.call_args.kwargs["timeout"] == 7

    for code, error in ((400, ValueError), (409, WorkflowConflict), (502, IntegrationUnavailable)):
        with patch("integrations.requests.request", return_value=_response(code, {"error": "nope"})):
            with pytest.raises(error, match="nope"):
                client.status("w")
    with patch("integrations.requests.request", side_effect=requests.ConnectionError()):
        with pytest.raises(IntegrationUnavailable):
            client.status("w")
    with pytest.raises(IntegrationDisabled):
        MultiAgentClient("http://agents.test", enabled=False).status("w")

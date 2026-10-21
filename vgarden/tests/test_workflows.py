"""Release 2: Virtual Garden <-> shared Multi-Agent Server (garden_workflows.py).

A FakeMultiAgent stands in for the server and follows its state machine
(received -> planning -> working -> reviewing -> awaiting_human_review -> a human
decision), so these tests cover the integration without Ollama or the server
running. Runs are made synchronous so each request sees the finished state.
"""

from datetime import date
from unittest.mock import Mock, patch

import pytest
import requests

from extensions import db
from integrations import (
    IntegrationDisabled,
    IntegrationUnavailable,
    MultiAgentClient,
    WorkflowConflict,
)
from models import Garden, GardenArea, GardenWorkflow, Planting, PlantingLocation

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
            "workflow_id": workflow_id, "task": task, "source": "vgarden",
            "status": "received", "history": [self._event("received")],
            "_evidence": evidence, "feedback": [],
        }
        return {"workflow_id": workflow_id, "task": task, "source": "vgarden", "status": "received"}

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
            plan={"steps": ["Read this garden's plantings", "Summarise them with citations"]
                  + [f"Address: {f}" for f in w["feedback"]]},
            evidence=evidence,
            result={"answer": "Backyard plantings: Tomato x3, flowering.",
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
    app.extensions["mcp"].enabled = False  # evidence from the local snapshot
    return fake


def _garden(app, owner_id=1, name="Backyard"):
    with app.app_context():
        garden = Garden(owner_id=owner_id, name=name, location_label="Melbourne", climate_zone="temperate")
        db.session.add(garden)
        db.session.flush()
        area = GardenArea(garden_id=garden.id, name="North bed", area_type="bed", width=2, length=3)
        db.session.add(area)
        db.session.flush()
        planting = Planting(garden_id=garden.id, crop_name="Tomato", quantity=3,
                            lifecycle_state="growing", growth_stage="flowering",
                            planted_date=date(2026, 9, 1))
        db.session.add(planting)
        db.session.flush()
        db.session.add(PlantingLocation(planting_id=planting.id, garden_area_id=area.id))
        db.session.commit()
        return garden.id


def _start(client, garden_id, task="What is growing in each area?", headers=HTMX):
    return client.post(f"/gardens/{garden_id}/workflows", data={"task": task}, headers=headers)


def _only_workflow(app):
    with app.app_context():
        return GardenWorkflow.query.one()


# --- start -> plan -> work -> review -> human review, through the UI routes ---


def test_start_sends_only_this_gardens_records_and_runs_to_human_review(app, client, login_as, agents):
    garden_id = _garden(app)
    _garden(app, owner_id=2, name="Neighbour")
    login_as(1)

    response = _start(client, garden_id)

    assert response.status_code == 201
    html = response.get_data(as_text=True)
    assert 'data-workflow-status="awaiting_human_review"' in html
    assert "Read this garden&#39;s plantings" in html  # Planner
    assert "Backyard plantings: Tomato x3, flowering." in html  # Worker
    assert 'data-review="accept"' in html  # Reviewer
    assert 'name="decision" value="request_changes"' in html  # Human review form
    assert "every 3s" not in html  # finished, so no polling

    sent = agents.created[0]
    assert sent["task"] == "What is growing in each area?"
    evidence = sent["evidence"]
    assert evidence["mode"] == "vgarden-api"
    ids = [p["chunk_id"] for p in evidence["passages"]]
    assert ids == [f"garden-{garden_id}-summary", f"garden-{garden_id}-areas", f"garden-{garden_id}-plantings"]
    text = "\n".join(p["text"] for p in evidence["passages"])
    assert ("Tomato - quantity 3; status growing; growth stage flowering; location area: North bed; "
            "planted 2026-09-01; expected harvest not recorded") in text
    assert "Neighbour" not in text
    assert all(p["title"].endswith("— Virtual Garden record") for p in evidence["passages"])

    workflow = _only_workflow(app)
    assert (workflow.garden_id, workflow.workflow_id, workflow.status) == (garden_id, "wf-1", "awaiting_human_review")


def test_evidence_is_read_through_mcp_when_enabled(app, client, login_as, agents):
    garden_id = _garden(app)
    login_as(1)
    snapshot = {"garden_id": garden_id, "name": "Backyard: east", "areas": [], "containers": [],
                "plantings": [{"crop_name": "Basil", "quantity": 2, "lifecycle_state": "sown"}]}
    app.extensions["mcp"] = Mock(enabled=True)
    app.extensions["mcp"].call.return_value = {"is_error": False, "structured_content": snapshot}

    assert _start(client, garden_id).status_code == 201

    app.extensions["mcp"].call.assert_called_once_with("get_garden_snapshot", garden_id)
    evidence = agents.created[0]["evidence"]
    assert evidence["mode"] == "mcp:get_garden_snapshot"
    assert evidence["passages"][0]["title"] == "Backyard east summary — Virtual Garden record"
    assert "Basil - quantity 2; status sown; growth stage not recorded" in evidence["passages"][-1]["text"]


def test_human_decisions_are_recorded_and_requested_changes_rerun(app, client, login_as, agents):
    garden_id = _garden(app)
    login_as(1)
    _start(client, garden_id)
    local_id = _only_workflow(app).id
    url = f"/gardens/{garden_id}/workflows/{local_id}/review"

    # Feedback is required for a request for changes; the error shows on the panel.
    missing = client.post(url, data={"decision": "request_changes"}, headers=HTMX)
    assert missing.status_code == 400
    assert "Explain the decision" in missing.get_data(as_text=True)
    assert client.post(url, data={"decision": "approve"}, headers=HTMX).status_code == 400

    # Requested changes start a revised run that comes back for review.
    revised = client.post(url, data={"decision": "request_changes", "feedback": "Include harvest dates"},
                          headers=HTMX)
    assert revised.status_code == 200
    html = revised.get_data(as_text=True)
    assert 'data-workflow-status="awaiting_human_review"' in html
    assert "Address: Include harvest dates" in html

    accepted = client.post(url, data={"decision": "accept"}, headers=HTMX)
    assert 'data-workflow-status="accepted"' in accepted.get_data(as_text=True)
    assert [r[1:] for r in agents.reviews] == [
        ("request_changes", "Include harvest dates", "vgarden-user-1"),
        ("accept", "", "vgarden-user-1"),
    ]
    statuses = [e["status"] for e in agents.workflows["wf-1"]["history"]]
    assert statuses.count("awaiting_human_review") == 2 and statuses[-1] == "accepted"
    assert _only_workflow(app).status == "accepted"

    # A finished workflow can't be reviewed again.
    assert client.post(url, data={"decision": "reject"}, headers=HTMX).status_code == 409


def test_json_clients_get_the_workflow_state(app, client, login_as, agents):
    garden_id = _garden(app)
    login_as(1)
    created = client.post(f"/gardens/{garden_id}/workflows", json={"task": "Summarise plantings"})
    assert created.status_code == 201
    body = created.get_json()
    assert body["status"] == "awaiting_human_review" and body["polling"] is False
    assert body["review"]["recommendation"] == "accept"

    reviewed = client.post(f"/gardens/{garden_id}/workflows/{body['id']}/review",
                           json={"decision": "partially_accept", "feedback": "Dates unconfirmed"})
    assert reviewed.get_json()["human_review"]["decision"] == "partially_accept"


def test_running_workflow_polls_until_the_agents_finish(app, client, login_as, agents):
    garden_id = _garden(app)
    login_as(1)
    queued = []
    app.extensions["multi_agent_runner"] = queued.append  # hold the run

    html = _start(client, garden_id).get_data(as_text=True)
    assert 'hx-trigger="every 3s"' in html and "Running locally" in html

    queued.pop()()  # the background run finishes
    local_id = _only_workflow(app).id
    done = client.get(f"/gardens/{garden_id}/workflows/{local_id}", headers=HTMX).get_data(as_text=True)
    assert "every 3s" not in done and 'data-workflow-status="awaiting_human_review"' in done


def test_failed_run_offers_a_retry(app, client, login_as, agents):
    garden_id = _garden(app)
    login_as(1)
    agents.run = Mock(side_effect=IntegrationUnavailable("Ollama down"))
    html = _start(client, garden_id).get_data(as_text=True)
    assert 'data-workflow-status="received"' in html and "Run workflow" in html

    del agents.run  # back to the fake's real run
    local_id = _only_workflow(app).id
    retried = client.post(f"/gardens/{garden_id}/workflows/{local_id}/run", headers=HTMX)
    assert retried.status_code == 202
    assert 'data-workflow-status="awaiting_human_review"' in retried.get_data(as_text=True)


# --- boundaries ---


def test_routes_are_owner_scoped(app, client, login_as, agents):
    mine = _garden(app)
    theirs = _garden(app, owner_id=2, name="Neighbour")
    login_as(2)
    _start(client, theirs)
    their_local = _only_workflow(app).id

    login_as(1)
    assert _start(client, theirs).status_code == 404
    for path in (f"/gardens/{theirs}/workflows/{their_local}", f"/gardens/{mine}/workflows/{their_local}"):
        assert client.get(path, headers=HTMX).status_code == 404
        assert client.post(path + "/run", headers=HTMX).status_code == 404
        assert client.post(path + "/review", data={"decision": "accept"}, headers=HTMX).status_code == 404
    assert len(agents.created) == 1 and agents.reviews == []


def test_login_is_required(app, client, agents):
    garden_id = _garden(app)
    response = _start(client, garden_id)
    assert response.status_code == 302
    assert agents.created == []


@pytest.mark.parametrize("task", ["", "   ", "x" * 501])
def test_task_is_validated_before_anything_is_sent(app, client, login_as, agents, task):
    garden_id = _garden(app)
    login_as(1)
    assert _start(client, garden_id, task=task).status_code == 400
    assert agents.created == []


def test_disabled_and_unreachable_server_create_nothing(app, client, login_as, agents):
    garden_id = _garden(app)
    login_as(1)
    agents.enabled = False
    assert _start(client, garden_id).status_code == 503
    agents.enabled, agents.unreachable = True, True
    assert _start(client, garden_id).status_code == 502
    with app.app_context():
        assert GardenWorkflow.query.count() == 0


def test_garden_page_shows_the_panel_or_the_disabled_state(app, client, login_as, agents):
    garden_id = _garden(app)
    login_as(1)
    _start(client, garden_id, task="Summarise plantings")
    page = client.get(f"/gardens/{garden_id}/view").get_data(as_text=True)
    assert "Agent workflow (Planner → Worker → Reviewer → you)" in page
    assert "Start workflow" in page and "Summarise plantings" in page

    agents.enabled = False
    page = client.get(f"/gardens/{garden_id}/view").get_data(as_text=True)
    assert 'data-integration="multi-agent-disabled"' in page and "Start workflow" not in page


def test_deleting_a_garden_removes_its_workflow_links(app, client, login_as, agents, service_headers):
    garden_id = _garden(app)
    login_as(1)
    _start(client, garden_id)
    assert client.delete(f"/gardens/{garden_id}", headers=service_headers).status_code == 204
    with app.app_context():
        assert GardenWorkflow.query.count() == 0


# --- the HTTP client's mapping of server responses ---


def _response(code, body):
    response = Mock(status_code=code)
    response.json.return_value = body
    return response


def test_client_maps_server_responses():
    client = MultiAgentClient("http://agents.test", timeout=7)
    with patch("integrations.requests.request", return_value=_response(201, {"workflow_id": "w"})) as call:
        assert client.create("Task", {"passages": []}) == {"workflow_id": "w"}
    assert call.call_args.kwargs["json"] == {"task": "Task", "source": "vgarden", "evidence": {"passages": []}}

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

"""Release 2: Plant Health <-> shared Multi-Agent Server (workflows.py).

A FakeMultiAgent stands in for the server and follows its state machine
(received -> planning -> working -> reviewing -> awaiting_human_review -> a human
decision), so these tests cover the integration without Ollama or the server
running. Runs are made synchronous so each request sees the finished state.
"""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import pytest
import requests

from extensions import db
from integrations import IntegrationDisabled, IntegrationUnavailable, MultiAgentClient, WorkflowConflict
from models import Assessment, HealthWorkflow

HTMX = {"HX-Request": "true"}
BASE = "/plant-health-records"


class FakeMultiAgent:
    """Speaks the Multi-Agent Server's contract; records what it was sent."""

    def __init__(self):
        self.enabled = True
        self.base_url = "http://agents.test"
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

    def status_check(self):
        self._check()
        return {"status": "ok"}

    def create(self, task, evidence):
        self._check()
        workflow_id = f"wf-{len(self.workflows) + 1}"
        self.created.append({"task": task, "evidence": evidence})
        self.workflows[workflow_id] = {
            "workflow_id": workflow_id, "task": task, "source": "health", "status": "received",
            "history": [self._event("received")], "_evidence": evidence, "_feedback": [],
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
            plan={"steps": ["Read the assessment's issues", "Compare with earlier assessments"]
                  + [f"Address: {f}" for f in w["_feedback"]]},
            evidence=evidence,
            result={"answer": "Tomato assessment: yellowing lower leaves is the main issue.",
                    "insufficient_context": False,
                    "cited_chunk_ids": [evidence["passages"][1]["chunk_id"]]},
            review={"recommendation": self.recommendation,
                    "issues": [] if self.recommendation == "accept" else ["Unsupported claim"]},
            models={"planner": "qwen3:4b-instruct", "worker": "qwen3:4b-instruct",
                    "reviewer": "qwen3:4b-instruct"},
        )
        w.pop("human_review", None)
        return self.status(workflow_id)

    def status(self, workflow_id):
        self._check()
        return {k: v for k, v in self.workflows[workflow_id].items() if not k.startswith("_")}

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
            w["_feedback"].append(feedback)
        return self.status(workflow_id)


@pytest.fixture
def agents(app):
    fake = FakeMultiAgent()
    app.extensions["multi_agent"] = fake
    app.extensions["multi_agent_runner"] = lambda go: go()  # run synchronously
    return fake


def _assessment(app, plant_ref="Tomato, back bed", days_ago=0, **fields):
    values = {
        "plant_ref": plant_ref, "description": "Lower leaves yellow, soil wet.", "has_image": False,
        "model": "fake-vision-model", "status": "at_risk", "health_score": 62, "score_band": "fair",
        "confidence": "medium", "confidence_reason": "No photo, description only.",
        "plant_identification": "Tomato", "summary": "Yellowing lower leaves; likely overwatering.",
        "issues_json": json.dumps([{"name": "Yellowing lower leaves", "severity": "moderate",
                                     "evidence": "Owner reports yellow lower leaves"}]),
        "recommendations_json": json.dumps([{"action": "Check soil moisture", "priority": "high",
                                              "details": "Let the top 2 cm dry before watering"}]),
        "missing_information_json": json.dumps(["No photo of the leaves"]),
        "created_at": datetime(2026, 10, 20, tzinfo=timezone.utc) - timedelta(days=days_ago),
    }
    values.update(fields)
    with app.app_context():
        record = Assessment(**values)
        db.session.add(record)
        db.session.commit()
        return record.id


def _start(client, assessment_id, task="Which issue needs attention first?", headers=HTMX):
    return client.post(f"{BASE}/assessments/{assessment_id}/workflows", data={"task": task}, headers=headers)


def _only_workflow(app):
    with app.app_context():
        return HealthWorkflow.query.one()


# --- start -> plan -> work -> review -> human review, through the UI routes ---


def test_start_sends_only_this_assessment_and_its_plants_history(app, client, agents):
    current = _assessment(app)
    earlier = _assessment(app, days_ago=10, status="healthy", health_score=81, summary="Looked healthy.")
    other = _assessment(app, plant_ref="Basil", summary="Basil is wilting.")

    response = _start(client, current)

    assert response.status_code == 201
    html = response.get_data(as_text=True)
    assert 'data-workflow-status="awaiting_human_review"' in html
    assert "Read the assessment&#39;s issues" in html  # Planner
    assert "yellowing lower leaves is the main issue." in html  # Worker
    assert 'data-review="accept"' in html  # Reviewer
    assert 'name="decision" value="request_changes"' in html  # Human review form
    assert "every 3s" not in html  # finished, so no polling

    evidence = agents.created[0]["evidence"]
    assert evidence["mode"] == "health-api"
    assert [p["chunk_id"] for p in evidence["passages"]] == [
        f"health-{current}-assessment", f"health-{current}-issues",
        f"health-{current}-recommendations", f"health-{current}-history"]
    text = "\n".join(p["text"] for p in evidence["passages"])
    assert "Health score: 62 (0-100), band fair" in text
    assert "Yellowing lower leaves - severity moderate; evidence Owner reports yellow lower leaves" in text
    assert "Check soil moisture - priority high; details Let the top 2 cm dry before watering" in text
    assert "Missing information: No photo of the leaves" in text
    assert "not a diagnosis" in text
    assert f"Assessment {earlier} on 2026-10-10: status healthy; health score 81" in text
    assert "Basil" not in text and f"Assessment {other}" not in text  # another plant's record never leaves
    assert all(p["title"].endswith("— Plant Health record") for p in evidence["passages"])

    workflow = _only_workflow(app)
    assert (workflow.assessment_id, workflow.workflow_id, workflow.status) == (current, "wf-1", "awaiting_human_review")


def test_gaps_are_stated_not_left_blank(app, client, agents):
    record = _assessment(app, plant_ref=None, health_score=None, confidence=None, issues_json="[]",
                         recommendations_json="[]", missing_information_json="[]", description=None)

    _start(client, record)

    evidence = agents.created[0]["evidence"]
    assert len(evidence["passages"]) == 3  # no plant name, so no history
    text = "\n".join(p["text"] for p in evidence["passages"])
    assert "Plant: not recorded" in text
    assert "Health score: not recorded" in text
    assert "No issues were recorded." in text
    assert "No recommendations were recorded." in text


def test_human_decisions_are_recorded_and_requested_changes_rerun(app, client, agents):
    record = _assessment(app)
    _start(client, record)
    url = f"{BASE}/assessments/{record}/workflows/{_only_workflow(app).id}/review"

    missing = client.post(url, data={"decision": "request_changes"}, headers=HTMX)
    assert missing.status_code == 400  # feedback required, nothing recorded
    assert agents.reviews == []

    changed = client.post(url, data={"decision": "request_changes", "feedback": "Mention the missing photo."},
                          headers=HTMX)
    assert changed.status_code == 200
    html = changed.get_data(as_text=True)
    assert "Address: Mention the missing photo." in html  # the revised run saw the feedback
    assert 'data-workflow-status="awaiting_human_review"' in html

    accepted = client.post(url, data={"decision": "accept"}, headers=HTMX)
    assert 'data-workflow-status="accepted"' in accepted.get_data(as_text=True)
    assert [(d, r) for _, d, _, r in agents.reviews] == [
        ("request_changes", "health-user-web"), ("accept", "health-user-web")]
    assert _only_workflow(app).status == "accepted"

    again = client.post(url, data={"decision": "reject"}, headers=HTMX)
    assert again.status_code == 409  # no second decision


@pytest.mark.parametrize("decision, status", [("partially_accept", "partially_accepted"), ("reject", "rejected")])
def test_other_decisions(app, client, agents, decision, status):
    record = _assessment(app)
    _start(client, record)
    url = f"{BASE}/assessments/{record}/workflows/{_only_workflow(app).id}/review"

    response = client.post(url, json={"decision": decision, "feedback": "Only the first issue is supported."})

    assert response.status_code == 200
    assert response.get_json()["status"] == status


def test_api_callers_may_label_themselves_but_not_with_anything(app, client, agents):
    record = _assessment(app)
    _start(client, record)
    url = f"{BASE}/assessments/{record}/workflows/{_only_workflow(app).id}/review"

    assert client.post(url, json={"decision": "accept", "reviewer_id": "bad id!"}).status_code == 400
    assert client.post(url, json={"decision": "accept", "reviewer_id": "yunus-terminal"}).status_code == 200
    assert agents.reviews[-1][3] == "yunus-terminal"


def test_json_api_returns_state_and_polling(app, client, agents):
    record = _assessment(app)
    body = _start(client, record, headers={"Accept": "application/json"}).get_json()
    assert body["status"] == "awaiting_human_review"
    assert body["assessment_id"] == record
    assert body["polling"] is False

    detail = client.get(f"{BASE}/assessments/{record}/workflows/{body['id']}")
    assert detail.get_json()["result"]["cited_chunk_ids"] == [f"health-{record}-issues"]


def test_a_running_workflow_polls(app, client, agents):
    record = _assessment(app)
    app.extensions["multi_agent_runner"] = lambda go: None  # never finishes

    html = _start(client, record).get_data(as_text=True)

    assert 'hx-trigger="every 3s"' in html
    assert "Running locally" in html


def test_failed_run_can_be_retried(app, client, agents):
    record = _assessment(app)
    app.extensions["multi_agent_runner"] = lambda go: None
    _start(client, record)
    workflow = _only_workflow(app)
    agents.workflows[workflow.workflow_id]["status"] = "failed"
    from workflows import _running
    _running.discard(workflow.workflow_id)
    app.extensions["multi_agent_runner"] = lambda go: go()

    html = client.post(f"{BASE}/assessments/{record}/workflows/{workflow.id}/run", headers=HTMX).get_data(as_text=True)

    assert 'data-workflow-status="awaiting_human_review"' in html


# --- boundaries ---


def test_workflow_must_belong_to_the_assessment(app, client, agents):
    first, second = _assessment(app), _assessment(app, plant_ref="Basil")
    _start(client, first)
    local_id = _only_workflow(app).id

    assert client.get(f"{BASE}/assessments/{second}/workflows/{local_id}").status_code == 404
    assert client.post(f"{BASE}/assessments/{second}/workflows/{local_id}/review",
                       data={"decision": "accept"}).status_code == 404
    assert client.get(f"{BASE}/assessments/999/workflows/{local_id}").status_code == 404
    assert _start(client, 999).status_code == 404
    assert agents.reviews == []


@pytest.mark.parametrize("task", ["", "   ", "x" * 501])
def test_task_is_validated(app, client, agents, task):
    record = _assessment(app)

    assert _start(client, record, task=task, headers={}).status_code == 400
    assert agents.created == []


@pytest.mark.parametrize("enabled, unreachable, code", [(False, False, 503), (True, True, 502)])
def test_disabled_or_unreachable_server_creates_nothing(app, client, agents, enabled, unreachable, code):
    record = _assessment(app)
    agents.enabled, agents.unreachable = enabled, unreachable

    assert _start(client, record, headers={}).status_code == code
    with app.app_context():
        assert HealthWorkflow.query.count() == 0


def test_page_shows_the_panel_or_the_disabled_note(app, client, agents):
    record = _assessment(app)
    page = client.get(f"{BASE}/{record}").get_data(as_text=True)
    assert "Agent workflow (Planner → Worker → Reviewer → you)" in page
    assert f'hx-post="{BASE}/assessments/{record}/workflows"' in page

    agents.enabled = False
    page = client.get(f"{BASE}/{record}").get_data(as_text=True)
    assert 'data-integration="multi-agent-disabled"' in page


def test_deleting_the_assessment_deletes_its_workflows(app, client, agents):
    record = _assessment(app)
    _start(client, record)

    assert client.delete(f"{BASE}/assessments/{record}").status_code in (200, 204)
    with app.app_context():
        assert HealthWorkflow.query.count() == 0


def test_integrations_reports_the_multi_agent_server(app, client, agents):
    body = client.get(f"{BASE}/integrations").get_json()
    assert body["multi_agent"] == {"enabled": True, "url": "http://agents.test", "reachable": True}

    agents.enabled = False
    assert client.get(f"{BASE}/integrations").get_json()["multi_agent"]["reachable"] is None


# --- the HTTP client ---


def _reply(status, body):
    response = Mock(status_code=status)
    response.json.return_value = body
    return response


def test_client_sends_the_health_source_and_maps_errors():
    client = MultiAgentClient("http://agents.test")
    with patch("integrations.requests.request", return_value=_reply(201, {"workflow_id": "w"})) as call:
        client.create("Why?", {"mode": "health-api", "passages": []})
    assert call.call_args.kwargs["json"]["source"] == "health"

    for status, error in ((400, ValueError), (409, WorkflowConflict), (500, IntegrationUnavailable)):
        with patch("integrations.requests.request", return_value=_reply(status, {"error": "no"})):
            with pytest.raises(error):
                client.status("w")
    with patch("integrations.requests.request", side_effect=requests.ConnectionError()):
        with pytest.raises(IntegrationUnavailable):
            client.status_check()
    with pytest.raises(IntegrationDisabled):
        MultiAgentClient("http://agents.test", enabled=False).status("w")
    with pytest.raises(ValueError):
        MultiAgentClient("file:///etc/passwd")

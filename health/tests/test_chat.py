"""The 'discuss this assessment' follow-up chat: Plan -> Act -> Observe -> Adapt,
stored conversation, and continuity across turns."""

from extensions import db
from models import Assessment, AssessmentAILoopRun, AssessmentChatMessage


def _make_assessment(client):
    client.post(
        "/plant-health-records/assessments",
        json={"plant_ref": "Tomato — north bed", "description": "Lower leaves yellowing."},
    )


def test_chat_runs_the_loop_and_stores_the_conversation(client, app):
    _make_assessment(client)
    with app.app_context():
        aid = Assessment.query.one().id

    resp = client.post(
        f"/plant-health-records/assessments/{aid}/chat",
        data={"question": "Why do you think it's underwatered?"},
    )
    assert resp.status_code == 200
    assert b"ease off watering" in resp.data
    assert "Plan → Act → Observe → Adapt".encode() in resp.data

    with app.app_context():
        msgs = AssessmentChatMessage.query.order_by(AssessmentChatMessage.id).all()
        assert [m.role for m in msgs] == ["user", "assistant"]
        run = AssessmentAILoopRun.query.one()
        assert run.assessment_id == aid
        assert run.verdict == "approved"
        assert [e["phase"] for e in run.trace] == ["plan", "act", "observe", "adapt"]


def test_chat_is_grounded_on_the_assessment_and_keeps_history(client, app):
    _make_assessment(client)
    with app.app_context():
        aid = Assessment.query.one().id

    client.post(f"/plant-health-records/assessments/{aid}/chat", data={"question": "first"})
    client.post(f"/plant-health-records/assessments/{aid}/chat", data={"question": "second"})

    fake = app.extensions["health_chat_ai"]
    first_grounding = fake.calls[0]["grounding"]
    assert first_grounding["assessment"]["status"] == "at_risk"
    assert first_grounding["assessment"]["gardener_description"] == "Lower leaves yellowing."
    # the second turn is handed the first exchange
    assert [m["content"] for m in fake.calls[-1]["grounding"]["conversation"]] == [
        "first",
        "About 'first': based on the assessment, ease off watering first.",
    ]


def test_reviewer_revision_loops(client, app):
    _make_assessment(client)
    app.extensions["ai_loop_reviewer"].script = ["revise", "approved"]
    with app.app_context():
        aid = Assessment.query.one().id

    client.post(f"/plant-health-records/assessments/{aid}/chat", data={"question": "q"})

    with app.app_context():
        assert AssessmentAILoopRun.query.one().iterations == 2


def test_chat_rejects_empty_and_missing(client, app):
    _make_assessment(client)
    with app.app_context():
        aid = Assessment.query.one().id
    assert client.post(
        f"/plant-health-records/assessments/{aid}/chat", data={"question": "  "}
    ).status_code == 400
    assert client.post(
        "/plant-health-records/assessments/999/chat", data={"question": "q"}
    ).status_code == 404


def test_clear_and_loop_trace_page(client, app):
    _make_assessment(client)
    with app.app_context():
        aid = Assessment.query.one().id
    client.post(f"/plant-health-records/assessments/{aid}/chat", data={"question": "q"})
    with app.app_context():
        run_id = AssessmentAILoopRun.query.one().id

    assert client.get(
        f"/plant-health-records/assessments/{aid}/chat/loop/{run_id}"
    ).status_code == 200

    client.post(f"/plant-health-records/assessments/{aid}/chat/clear")
    with app.app_context():
        assert AssessmentChatMessage.query.count() == 0
        assert AssessmentAILoopRun.query.count() == 0


def test_deleting_an_assessment_cascades_the_chat(client, app):
    _make_assessment(client)
    with app.app_context():
        aid = Assessment.query.one().id
    client.post(f"/plant-health-records/assessments/{aid}/chat", data={"question": "q"})
    client.delete(f"/plant-health-records/assessments/{aid}")
    with app.app_context():
        assert db.session.get(Assessment, aid) is None
        assert AssessmentChatMessage.query.count() == 0
        assert AssessmentAILoopRun.query.count() == 0

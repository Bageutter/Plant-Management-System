import pytest

from ai import AIUnavailableError
from extensions import db
from models import (
    Container,
    Garden,
    GardenAILoopRun,
    GardenArea,
    GardenChatMessage,
    Planting,
    PlantingLocation,
)


class FakeGardenAI:
    """Stand-in drafter. `.draft(question, grounding, feedback)` is the loop's ACT step."""

    def __init__(self, answer="ok", error=None):
        self.answer = answer
        self.error = error
        self.calls = []

    def draft(self, question, grounding, feedback=None):
        self.calls.append({"question": question, "grounding": grounding, "feedback": feedback})
        if self.error:
            raise self.error
        return self.answer

    # convenience accessors for assertions
    def garden_context(self, i=0):
        return self.calls[i]["grounding"]["garden"]

    def history(self, i=0):
        return self.calls[i]["grounding"]["conversation"]


@pytest.fixture
def fake_ai(app):
    fake = FakeGardenAI()
    app.extensions["garden_ai"] = fake
    return fake


def _seed_garden(app, owner_id=1, latitude=None, longitude=None):
    with app.app_context():
        garden = Garden(
            owner_id=owner_id, name="Backyard", latitude=latitude, longitude=longitude
        )
        db.session.add(garden)
        db.session.commit()

        area = GardenArea(garden_id=garden.id, name="North bed", area_type="bed")
        db.session.add(area)
        db.session.commit()

        container = Container(garden_area_id=area.id, name="Patio pot", container_type="pot")
        db.session.add(container)
        db.session.commit()

        planting = Planting(garden_id=garden.id, crop_name="Roma tomato", lifecycle_state="growing")
        db.session.add(planting)
        db.session.flush()
        db.session.add(PlantingLocation(planting_id=planting.id, garden_area_id=area.id))
        db.session.commit()
        return garden.id


def test_ask_requires_login(app, client):
    garden_id = _seed_garden(app)
    response = client.post(f"/gardens/{garden_id}/ai/ask", data={"question": "hi"})
    assert response.status_code == 302
    assert response.headers["Location"] == "http://auth.test/login"


def test_ask_404s_for_non_owner(app, client, login_as, fake_ai):
    garden_id = _seed_garden(app, owner_id=1)
    login_as(2)
    response = client.post(f"/gardens/{garden_id}/ai/ask", data={"question": "hi"})
    assert response.status_code == 404


def test_ask_rejects_empty_question(app, client, login_as, fake_ai):
    garden_id = _seed_garden(app)
    login_as(1)
    response = client.post(f"/gardens/{garden_id}/ai/ask", data={"question": "   "})
    assert response.status_code == 400
    assert b"Enter a question" in response.data
    with app.app_context():
        assert GardenChatMessage.query.count() == 0


def test_ask_grounds_on_the_garden_snapshot_and_persists_a_loop_run(app, client, login_as):
    garden_id = _seed_garden(app)
    fake = FakeGardenAI("Your Roma tomato is growing in the North bed.")
    app.extensions["garden_ai"] = fake
    login_as(1)

    response = client.post(
        f"/gardens/{garden_id}/ai/ask", data={"question": "What's growing?"}
    )

    assert response.status_code == 200
    assert b"Roma tomato is growing in the North bed" in response.data
    assert "Plan → Act → Observe → Adapt".encode() in response.data  # loop badge

    call = fake.calls[0]
    assert call["question"] == "What's growing?"
    assert call["feedback"] is None
    crop_names = [p["crop_name"] for p in fake.garden_context()["plantings"]]
    assert "Roma tomato" in crop_names
    assert fake.garden_context()["areas"][0]["name"] == "North bed"
    assert fake.history() == []
    assert fake.garden_context()["weather"] is None
    assert fake.garden_context()["coordinates"] is None

    with app.app_context():
        rows = GardenChatMessage.query.order_by(GardenChatMessage.id).all()
        assert [r.role for r in rows] == ["user", "assistant"]
        run = GardenAILoopRun.query.one()
        assert run.garden_id == garden_id
        assert run.message_id == rows[1].id
        assert run.iterations == 1
        assert run.verdict == "approved"
        phases = [e["phase"] for e in run.trace]
        assert phases == ["plan", "act", "observe", "adapt"]


def test_reviewer_revision_loops_and_carries_feedback(app, client, login_as, ai_loop_reviewer):
    garden_id = _seed_garden(app)
    fake = FakeGardenAI("draft answer")
    app.extensions["garden_ai"] = fake
    ai_loop_reviewer.script = ["revise", "approved"]
    login_as(1)

    client.post(f"/gardens/{garden_id}/ai/ask", data={"question": "What's growing?"})

    assert len(fake.calls) == 2
    assert fake.calls[0]["feedback"] is None
    assert fake.calls[1]["feedback"] == "fix iteration 1"
    with app.app_context():
        run = GardenAILoopRun.query.one()
        assert run.iterations == 2
        assert run.verdict == "approved"
        assert [e["phase"] for e in run.trace] == [
            "plan", "act", "observe", "adapt", "act", "observe", "adapt"
        ]


def test_reviewer_never_satisfied_caps_iterations(app, client, login_as, ai_loop_reviewer):
    garden_id = _seed_garden(app)
    app.extensions["garden_ai"] = FakeGardenAI("still wrong")
    ai_loop_reviewer.script = ["revise"]  # always
    login_as(1)

    client.post(f"/gardens/{garden_id}/ai/ask", data={"question": "q"})

    with app.app_context():
        run = GardenAILoopRun.query.one()
        assert run.iterations == 2  # AI_LOOP_MAX_ITERATIONS
        assert run.verdict == "revised_capped"


def test_single_shot_when_no_reviewer(app, client, login_as):
    garden_id = _seed_garden(app)
    app.extensions["garden_ai"] = FakeGardenAI("one and done")
    app.extensions["ai_loop_reviewer"] = None
    login_as(1)

    client.post(f"/gardens/{garden_id}/ai/ask", data={"question": "q"})

    with app.app_context():
        run = GardenAILoopRun.query.one()
        assert run.verdict == "fallback"
        assert run.iterations == 1
        assert [e["phase"] for e in run.trace] == ["plan", "fallback"]


def test_loop_writes_jsonl_and_transcript(app, client, login_as):
    garden_id = _seed_garden(app)
    app.extensions["garden_ai"] = FakeGardenAI("logged")
    login_as(1)

    client.post(f"/gardens/{garden_id}/ai/ask", data={"question": "q"})

    import json
    import os

    log_dir = app.config["AI_LOOP_LOG_DIR"]
    jsonl = os.path.join(log_dir, "vgarden.jsonl")
    events = [json.loads(line) for line in open(jsonl, encoding="utf-8")]
    assert {e["phase"] for e in events} == {"plan", "act", "observe", "adapt"}
    with app.app_context():
        run = GardenAILoopRun.query.one()
        assert os.path.isfile(run.transcript_path)
        assert "Plan" in open(run.transcript_path, encoding="utf-8").read()


def test_loop_trace_page_is_owner_scoped(app, client, login_as):
    garden_id = _seed_garden(app, owner_id=1)
    app.extensions["garden_ai"] = FakeGardenAI("trace me")
    login_as(1)
    client.post(f"/gardens/{garden_id}/ai/ask", data={"question": "q"})
    with app.app_context():
        run_id = GardenAILoopRun.query.one().id

    assert client.get(f"/gardens/{garden_id}/ai/loop/{run_id}").status_code == 200
    login_as(2)
    assert client.get(f"/gardens/{garden_id}/ai/loop/{run_id}").status_code == 404


def test_weather_is_included_when_the_garden_has_coordinates(app, client, login_as, weather):
    garden_id = _seed_garden(app, latitude=-37.81, longitude=144.96)
    fake = FakeGardenAI("Rain tomorrow - hold off watering.")
    app.extensions["garden_ai"] = fake
    weather.raise_error = False
    weather.weather_result = {
        "as_of": "2026-09-02T00:00Z",
        "current": {"temperature_c": 14.0, "conditions": "Overcast"},
        "forecast": [{"date": "2026-09-03", "conditions": "Slight rain", "precipitation_mm": 4.2}],
    }
    login_as(1)

    client.post(f"/gardens/{garden_id}/ai/ask", data={"question": "Should I water?"})

    ctx = fake.garden_context()
    assert ctx["coordinates"] == {"latitude": -37.81, "longitude": 144.96}
    assert ctx["weather"]["current"]["conditions"] == "Overcast"
    assert weather.weather_calls == [(-37.81, 144.96)]


def test_weather_outage_does_not_break_the_chat(app, client, login_as, weather):
    garden_id = _seed_garden(app, latitude=1.0, longitude=2.0)
    fake = FakeGardenAI("ok")
    app.extensions["garden_ai"] = fake
    weather.raise_error = True
    login_as(1)

    response = client.post(f"/gardens/{garden_id}/ai/ask", data={"question": "hi"})

    assert response.status_code == 200
    assert fake.garden_context()["weather"] is None


def test_follow_up_question_passes_prior_history(app, client, login_as):
    garden_id = _seed_garden(app)
    fake = FakeGardenAI("answer")
    app.extensions["garden_ai"] = fake
    login_as(1)

    client.post(f"/gardens/{garden_id}/ai/ask", data={"question": "first"})
    client.post(f"/gardens/{garden_id}/ai/ask", data={"question": "second"})

    second_call = fake.calls[1]
    assert [m["role"] for m in second_call["grounding"]["conversation"]] == ["user", "assistant"]
    assert second_call["grounding"]["conversation"][0]["content"] == "first"


def test_ask_reports_unavailable_model(app, client, login_as):
    garden_id = _seed_garden(app)
    app.extensions["garden_ai"] = FakeGardenAI(error=AIUnavailableError("down"))
    login_as(1)

    response = client.post(
        f"/gardens/{garden_id}/ai/ask", data={"question": "What's growing?"}
    )

    assert response.status_code == 503
    assert b"local AI model is unavailable" in response.data
    with app.app_context():
        assert GardenChatMessage.query.count() == 0
        assert GardenAILoopRun.query.count() == 0


def test_answer_is_html_escaped(app, client, login_as):
    garden_id = _seed_garden(app)
    app.extensions["garden_ai"] = FakeGardenAI("<script>alert(1)</script>")
    login_as(1)

    response = client.post(f"/gardens/{garden_id}/ai/ask", data={"question": "x"})

    assert b"<script>alert(1)</script>" not in response.data
    assert b"&lt;script&gt;" in response.data


def test_history_and_clear_are_scoped_per_garden(app, client, login_as):
    garden_a = _seed_garden(app, owner_id=1)
    garden_b = _seed_garden(app, owner_id=1)
    app.extensions["garden_ai"] = FakeGardenAI("garden A answer")
    login_as(1)

    client.post(f"/gardens/{garden_a}/ai/ask", data={"question": "about A"})

    page_b = client.get(f"/gardens/{garden_b}/view")
    assert b"garden A answer" not in page_b.data

    client.post(f"/gardens/{garden_b}/ai/clear")
    with app.app_context():
        assert GardenChatMessage.query.filter_by(garden_id=garden_a).count() == 2
        assert GardenChatMessage.query.filter_by(garden_id=garden_b).count() == 0

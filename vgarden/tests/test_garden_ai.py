import pytest

from ai import AIUnavailableError
from extensions import db
from models import Container, Garden, GardenArea, GardenChatMessage, Planting, PlantingLocation


class FakeGardenAI:
    def __init__(self, response=None, error=None):
        self.response = response or {"answer": "ok"}
        self.error = error
        self.calls = []

    def ask(self, question, garden_context, history):
        self.calls.append(
            {"question": question, "garden_context": garden_context, "history": history}
        )
        if self.error:
            raise self.error
        return self.response


@pytest.fixture
def fake_ai(app):
    fake = FakeGardenAI()
    app.extensions["garden_ai"] = fake
    return fake


def _seed_garden(app, owner_id=1):
    with app.app_context():
        garden = Garden(owner_id=owner_id, name="Backyard")
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


def test_ask_grounds_on_the_garden_snapshot_and_persists(app, client, login_as):
    garden_id = _seed_garden(app)
    fake = FakeGardenAI({"answer": "Your Roma tomato is growing in the North bed."})
    app.extensions["garden_ai"] = fake
    login_as(1)

    response = client.post(
        f"/gardens/{garden_id}/ai/ask", data={"question": "What's growing?"}
    )

    assert response.status_code == 200
    assert b"Roma tomato is growing in the North bed" in response.data

    call = fake.calls[0]
    assert call["question"] == "What's growing?"
    crop_names = [p["crop_name"] for p in call["garden_context"]["plantings"]]
    assert "Roma tomato" in crop_names
    assert call["garden_context"]["areas"][0]["name"] == "North bed"
    assert call["history"] == []

    with app.app_context():
        rows = GardenChatMessage.query.order_by(GardenChatMessage.id).all()
        assert [r.role for r in rows] == ["user", "assistant"]
        assert rows[0].garden_id == garden_id


def test_follow_up_question_passes_prior_history(app, client, login_as):
    garden_id = _seed_garden(app)
    fake = FakeGardenAI({"answer": "answer"})
    app.extensions["garden_ai"] = fake
    login_as(1)

    client.post(f"/gardens/{garden_id}/ai/ask", data={"question": "first"})
    client.post(f"/gardens/{garden_id}/ai/ask", data={"question": "second"})

    assert [m["role"] for m in fake.calls[1]["history"]] == ["user", "assistant"]
    assert fake.calls[1]["history"][0]["content"] == "first"


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


def test_answer_is_html_escaped(app, client, login_as):
    garden_id = _seed_garden(app)
    app.extensions["garden_ai"] = FakeGardenAI({"answer": "<script>alert(1)</script>"})
    login_as(1)

    response = client.post(f"/gardens/{garden_id}/ai/ask", data={"question": "x"})

    assert b"<script>alert(1)</script>" not in response.data
    assert b"&lt;script&gt;" in response.data


def test_history_and_clear_are_scoped_per_garden(app, client, login_as):
    garden_a = _seed_garden(app, owner_id=1)
    garden_b = _seed_garden(app, owner_id=1)
    app.extensions["garden_ai"] = FakeGardenAI({"answer": "garden A answer"})
    login_as(1)

    client.post(f"/gardens/{garden_a}/ai/ask", data={"question": "about A"})

    page_b = client.get(f"/gardens/{garden_b}/view")
    assert b"garden A answer" not in page_b.data

    client.post(f"/gardens/{garden_b}/ai/clear")
    with app.app_context():
        assert GardenChatMessage.query.filter_by(garden_id=garden_a).count() == 2
        assert GardenChatMessage.query.filter_by(garden_id=garden_b).count() == 0

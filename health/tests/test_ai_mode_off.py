"""AI-Mode off (AI_MODE_ENABLED=false, the cloud baseline).

No model is ever called, yet records can still be created, read, edited and
deleted: a new record is saved "not assessed". With AI-Mode on, an unreachable
model still means a 503 and nothing saved (tests/test_endpoints.py).
"""

import json

import pytest

BASE = "/plant-health-records"


@pytest.fixture
def ai_off(app, fake_ai):
    app.config["AI_MODE_ENABLED"] = False
    fake_ai.reachable = False  # as in the cloud: there is no model to reach
    return fake_ai


def test_create_saves_a_not_assessed_record_without_calling_a_model(client, ai_off):
    response = client.post(f"{BASE}/assessments", json={"plant_ref": "Basil", "description": "Wilting at noon."})

    assert response.status_code == 201
    record = response.get_json()
    assert record["ai_mode"] == "disabled"
    assert record["status"] == "unknown"
    assert record["health_score"] is None and record["confidence"] is None
    assert record["description"] == "Wilting at noon."
    assert "AI assessment is turned off in this deployment" in record["summary"]
    assert ai_off.calls == []


def test_full_crud_works_with_ai_off(client, ai_off):
    created = client.post(f"{BASE}/assessments", json={"plant_ref": "Basil", "description": "Wilting."}).get_json()
    record_id = created["id"]

    listed = client.get(f"{BASE}/assessments").get_json()
    assert [r["id"] for r in listed] == [record_id]
    assert client.get(f"{BASE}/assessments/{record_id}").get_json()["plant_ref"] == "Basil"

    edited = client.patch(f"{BASE}/assessments/{record_id}", json={"description": "Wilting, soil dry."})
    assert edited.status_code == 200
    assert edited.get_json()["description"] == "Wilting, soil dry."

    assert client.delete(f"{BASE}/assessments/{record_id}").status_code in (200, 204)
    assert client.get(f"{BASE}/assessments/{record_id}").status_code == 404
    assert ai_off.calls == []


def test_the_page_form_saves_and_shows_the_record(client, ai_off):
    response = client.post(f"{BASE}/assessments", data={"plant_ref": "Basil", "description": "Wilting."},
                           headers={"HX-Request": "true"})

    assert response.status_code == 200
    assert b"AI assessment is turned off in this deployment" in response.data


def test_the_streaming_form_ends_with_the_saved_record(client, ai_off):
    response = client.post(f"{BASE}/assessments/stream", data={"plant_ref": "Basil", "description": "Wilting."})

    events = [json.loads(part[len("data: "):]) for part in response.get_data(as_text=True).split("\n\n") if part]
    assert response.mimetype == "text/event-stream"
    assert events[-1]["type"] == "done" and events[-1]["ai_mode"] == "disabled"
    assert "AI assessment is turned off" in events[-1]["html"]
    assert ai_off.calls == []


def test_generate_again_explains_that_ai_is_off(client, ai_off):
    record_id = client.post(f"{BASE}/assessments", json={"description": "Wilting."}).get_json()["id"]

    again = client.post(f"{BASE}/assessments/{record_id}/regenerate")
    assert again.status_code == 503
    assert "turned off in this deployment" in again.get_json()["error"]

    streamed = client.post(f"{BASE}/assessments/{record_id}/regenerate/stream").get_data(as_text=True)
    assert "turned off in this deployment" in streamed
    assert ai_off.calls == []


def test_ai_on_but_unreachable_still_saves_nothing(app, client, fake_ai):
    app.config["AI_MODE_ENABLED"] = True
    fake_ai.reachable = False

    response = client.post(f"{BASE}/assessments", json={"description": "Wilting."})

    assert response.status_code == 503
    assert client.get(f"{BASE}/assessments").get_json() == []

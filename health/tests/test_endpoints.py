"""Release 2 post-commit endpoint tests for the two assigned Plant Health backend
functions, run by name in .github/workflows/health.yml:

- ``routes.create_assessment`` POST /plant-health-records/assessments
- ``routes.list_assessments``   GET  /plant-health-records/assessments

Each test covers one function end to end: input validation, the error paths, the
success response, and what is (or is not) written to the database. Temporary
SQLite per test, a fake Ollama client, no live MCP/RAG/Ollama needed.
"""

from __future__ import annotations

import base64
import io

from PIL import Image

from models import Assessment, AssessmentLoopRun, Plant

RECORDS = "/plant-health-records/assessments"


def _counts(app) -> tuple[int, int, int]:
    with app.app_context():
        return Assessment.query.count(), AssessmentLoopRun.query.count(), Plant.query.count()


def _png_data_url(colour: str = "green", size: int = 8) -> str:
    buffer = io.BytesIO()
    Image.new("RGB", (size, size), colour).save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def test_create_assessment_validates_input_and_persists(app, client, fake_ai):
    # Validation: each bad body is a 400 with a reason, and nothing is written or
    # sent to the model.
    bad_bodies = [
        ({}, "Provide an image, a text description, or both."),
        ({"plant_ref": "Tomato"}, "Provide an image"),  # a name alone is not an assessment
        ({"description": "x" * 4001}, "4000 characters or fewer"),
        ({"plant_ref": "x" * 201, "description": "ok"}, "200 characters or fewer"),
        ({"plant_ref": 5, "description": "ok"}, "plant_ref must be a string"),
        ({"description": "ok", "image_base64": ""}, "non-empty base64"),
        ({"description": "ok", "image_base64": "data:image/png;base64,"}, "malformed"),
        ({"description": "ok", "image_base64": "not base64!!"}, "not valid base64"),
        ({"description": "ok", "image_base64": "data:image/bmp;base64,AAAA"}, "Unsupported image type"),
    ]
    for body, reason in bad_bodies:
        response = client.post(RECORDS, json=body)
        assert response.status_code == 400, body
        assert reason in response.get_json()["error"], body
    # A multipart upload of the wrong type is refused before any decoding.
    wrong_type = client.post(
        RECORDS,
        data={"description": "ok", "image": (io.BytesIO(b"hello"), "notes.txt", "text/plain")},
        content_type="multipart/form-data",
    )
    assert wrong_type.status_code == 400
    assert "Unsupported image type 'text/plain'" in wrong_type.get_json()["error"]
    assert fake_ai.calls == []

    # The local model being down is a 503, and still nothing is written.
    fake_ai.reachable = False
    outage = client.post(RECORDS, json={"description": "Wilting"})
    assert outage.status_code == 503 and "local AI" in outage.get_json()["error"]
    fake_ai.reachable = True
    assert _counts(app) == (0, 0, 0)

    # Success: trimmed inputs, the model's structured verdict, 201 with the record.
    response = client.post(
        RECORDS, json={"plant_ref": "  Tomato, back bed  ", "description": "Lower leaves yellow."}
    )
    assert response.status_code == 201
    body = response.get_json()
    assert body["plant_ref"] == "Tomato, back bed"
    assert body["description"] == "Lower leaves yellow."
    assert body["has_image"] is False and body["image_mime"] is None
    assert body["model"] == "fake-vision-model"
    assert (body["status"], body["health_score"], body["confidence"]) == ("at_risk", 45, "medium")
    assert body["issues"][0]["name"] == "Overwatering"
    assert body["recommendations"][0]["action"] == "Reduce watering"
    assert body["missing_information"] == ["A photo of the affected leaves"]
    assert body["loop"] == {
        "run_id": body["loop"]["run_id"],
        "iterations": 1,
        "verdict": "approved",
        "reviewed": True,
    }
    assert body["created_at"]
    # The model saw exactly the cleaned inputs, with no history for a new plant.
    sent = fake_ai.calls[-1]
    assert (sent["plant_ref"], sent["description"], sent["image"]) == ("Tomato, back bed", "Lower leaves yellow.", False)
    assert sent["history"] == []

    # Persistence: one record, its loop run, and the plant name registered as a title;
    # all readable back through the API.
    assert _counts(app) == (1, 1, 1)
    fetched = client.get(f"{RECORDS}/{body['id']}")
    assert fetched.status_code == 200 and fetched.get_json() == body
    assert [p["name"] for p in client.get("/plant-health-records/plants").get_json()] == ["Tomato, back bed"]

    # A second assessment of the same plant gets the first as history, and the
    # existing title is reused rather than duplicated (case-insensitive).
    again = client.post(RECORDS, json={"plant_ref": "tomato, BACK bed", "description": "Still yellow."})
    assert again.status_code == 201
    assert [h["id"] for h in fake_ai.calls[-1]["history"]] == [body["id"]]
    assert _counts(app) == (2, 2, 1)

    # A photo sent as a data URL is decoded, validated, stored and served back.
    with_photo = client.post(RECORDS, json={"description": "Spots on leaves", "image_base64": _png_data_url()})
    assert with_photo.status_code == 201
    photo = with_photo.get_json()
    assert photo["has_image"] is True and photo["image_mime"] in ("image/png", "image/jpeg")
    assert fake_ai.calls[-1]["image"] is True
    image = client.get(f"/plant-health-records/{photo['id']}/image")
    assert image.status_code == 200 and image.mimetype == photo["image_mime"]
    assert Image.open(io.BytesIO(image.data)).size == (8, 8)
    assert "image_data" not in photo and "image_base64" not in photo  # bytes never in JSON

    # The page's form (HTMX) gets the rendered record instead of JSON.
    fragment = client.post(
        RECORDS, data={"plant_ref": "Chilli", "description": "Curling leaves"}, headers={"HX-Request": "true"}
    )
    assert fragment.status_code == 200
    html = fragment.get_data(as_text=True)
    assert "<article" in html and "Chilli" in html and "Reduce watering" in html
    assert _counts(app) == (4, 4, 2)


def test_list_assessments_filters_pages_and_makes_no_writes(app, client, fake_ai):
    assert client.get(RECORDS).get_json() == []

    # Three records with distinct verdicts, so every filter has something to select.
    fake_ai.script = [
        {"status": "healthy", "health_score": 90},
        {"status": "at_risk", "health_score": 45},
        {"status": "unhealthy", "health_score": 20},
    ]
    ids = []
    for plant_ref in ("Tomato", "Basil", "Tomato"):
        created = client.post(RECORDS, json={"plant_ref": plant_ref, "description": f"About {plant_ref}"})
        assert created.status_code == 201
        ids.append(created.get_json()["id"])
    tomato_1, basil, tomato_2 = ids

    # Default listing: everything, newest first, each item the full record.
    response = client.get(RECORDS)
    assert response.status_code == 200
    everything = response.get_json()
    assert [r["id"] for r in everything] == [tomato_2, basil, tomato_1]
    assert [r["status"] for r in everything] == ["unhealthy", "at_risk", "healthy"]
    assert everything[0]["description"] == "About Tomato" and everything[0]["loop"]["verdict"] == "approved"

    # plant_ref is an exact match.
    assert [r["id"] for r in client.get(f"{RECORDS}?plant_ref=Tomato").get_json()] == [tomato_2, tomato_1]
    assert client.get(f"{RECORDS}?plant_ref=Capsicum").get_json() == []

    # status must be one of the known verdicts.
    assert [r["id"] for r in client.get(f"{RECORDS}?status=healthy").get_json()] == [tomato_1]
    assert [r["id"] for r in client.get(f"{RECORDS}?status=unhealthy&plant_ref=Tomato").get_json()] == [tomato_2]
    bad_status = client.get(f"{RECORDS}?status=dead")
    assert bad_status.status_code == 400
    assert "status must be one of: healthy, at_risk, unhealthy, unknown" == bad_status.get_json()["error"]

    # since is an ISO-8601 timestamp (a trailing Z is accepted); records at or after it.
    middle = next(r for r in everything if r["id"] == basil)["created_at"]
    since = [r["id"] for r in client.get(f"{RECORDS}?since={middle}").get_json()]
    assert basil in since and tomato_2 in since
    assert client.get(f"{RECORDS}?since=2000-01-01T00:00:00Z").get_json() == everything
    assert client.get(f"{RECORDS}?since=2999-01-01T00:00:00Z").get_json() == []
    bad_since = client.get(f"{RECORDS}?since=yesterday")
    assert bad_since.status_code == 400 and "ISO-8601" in bad_since.get_json()["error"]

    # Paging: limit is clamped to 1..200, offset to >= 0, and a page past the end is empty.
    assert [r["id"] for r in client.get(f"{RECORDS}?limit=2").get_json()] == [tomato_2, basil]
    assert [r["id"] for r in client.get(f"{RECORDS}?limit=2&offset=1").get_json()] == [basil, tomato_1]
    assert [r["id"] for r in client.get(f"{RECORDS}?limit=0").get_json()] == [tomato_2]  # clamped up to 1
    assert [r["id"] for r in client.get(f"{RECORDS}?limit=999&offset=-5").get_json()] == [tomato_2, basil, tomato_1]
    assert client.get(f"{RECORDS}?limit=2&offset=5").get_json() == []
    assert client.get(f"{RECORDS}?limit=abc").get_json() == everything  # unparsable -> default

    # Image bytes never travel in the listing (the MCP and RAG servers page through
    # it); only the flag and type do.
    with_photo = client.post(RECORDS, json={"description": "Spots", "image_base64": _png_data_url()})
    assert with_photo.status_code == 201
    newest = client.get(f"{RECORDS}?limit=1").get_json()[0]
    assert newest["id"] == with_photo.get_json()["id"] and newest["has_image"] is True
    assert "image_data" not in newest and "image_base64" not in newest

    # Read-only: however it is queried, the listing changes nothing and repeats exactly.
    before = _counts(app)
    model_calls = len(fake_ai.calls)
    for query in ("", "?plant_ref=Tomato", "?status=healthy", "?limit=1&offset=1", f"?since={middle}"):
        assert client.get(RECORDS + query).get_json() == client.get(RECORDS + query).get_json()
    assert _counts(app) == before and len(fake_ai.calls) == model_calls

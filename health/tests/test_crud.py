"""End-to-end CRUD tests for the Plant Health API and pages (fake model)."""

from __future__ import annotations

from conftest import make_assessment


def test_root_redirects_and_index_renders(client):
    assert client.get("/").status_code == 302
    page = client.get("/plant-health-records/")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert "Plant Health Records" in html
    assert "No assessments yet" in html


def test_healthz_reflects_local_ai_reachability(client, fake_ai):
    ok = client.get("/healthz")
    assert ok.status_code == 200 and ok.get_json()["status"] == "ok"
    fake_ai.reachable = False
    degraded = client.get("/healthz")
    assert degraded.status_code == 503 and degraded.get_json()["ai"]["reachable"] is False


def test_create_read_update_delete_roundtrip(client, fake_ai):
    created = make_assessment(client)
    assert created["status"] == "at_risk" and created["health_score"] == 45
    assert created["plant_ref"] == "Tomato, back bed"
    assert fake_ai.calls[-1]["plant_ref"] == "Tomato, back bed"
    record_id = created["id"]

    fetched = client.get(f"/plant-health-records/assessments/{record_id}")
    assert fetched.status_code == 200 and fetched.get_json()["summary"] == created["summary"]

    page = client.get(f"/plant-health-records/{record_id}")
    assert page.status_code == 200 and b"Tomato, back bed" in page.data

    patched = client.patch(
        f"/plant-health-records/assessments/{record_id}", json={"plant_ref": "Tomato, east end"}
    )
    assert patched.status_code == 200
    assert patched.get_json()["plant_ref"] == "Tomato, east end"
    assert patched.get_json()["description"] == "Lower leaves yellow, soil wet."  # untouched

    replaced = client.put(
        f"/plant-health-records/assessments/{record_id}", json={"description": "Only a description."}
    )
    assert replaced.get_json()["plant_ref"] is None  # PUT clears omitted fields

    deleted = client.delete(f"/plant-health-records/assessments/{record_id}")
    assert deleted.status_code == 204
    assert client.get(f"/plant-health-records/assessments/{record_id}").status_code == 404
    assert client.delete(f"/plant-health-records/assessments/{record_id}").status_code == 404


def test_validation_and_ai_outage(client, fake_ai):
    empty = client.post("/plant-health-records/assessments", json={})
    assert empty.status_code == 400 and "Provide an image" in empty.get_json()["error"]

    too_long = client.post("/plant-health-records/assessments", json={"description": "x" * 4001})
    assert too_long.status_code == 400

    bad_edit = client.patch("/plant-health-records/assessments/1", json={"plant_ref": 5})
    assert bad_edit.status_code == 404  # no record yet
    make_assessment(client)
    bad_edit = client.patch("/plant-health-records/assessments/1", json={"plant_ref": 5})
    assert bad_edit.status_code == 400 and "must be a string" in bad_edit.get_json()["error"]

    fake_ai.reachable = False
    outage = client.post("/plant-health-records/assessments", json={"description": "Wilting"})
    assert outage.status_code == 503 and "local AI" in outage.get_json()["error"]


def test_list_supports_filters_paging_and_since(client):
    ids = [make_assessment(client, plant_ref=ref)["id"] for ref in ("Tomato", "Basil", "Tomato")]

    everything = client.get("/plant-health-records/assessments").get_json()
    assert [r["id"] for r in everything] == ids[::-1]  # newest first

    tomatoes = client.get("/plant-health-records/assessments?plant_ref=Tomato").get_json()
    assert [r["id"] for r in tomatoes] == [ids[2], ids[0]]

    assert client.get("/plant-health-records/assessments?status=at_risk").get_json() == everything
    assert client.get("/plant-health-records/assessments?status=healthy").get_json() == []
    bad_status = client.get("/plant-health-records/assessments?status=dead")
    assert bad_status.status_code == 400

    page = client.get("/plant-health-records/assessments?limit=2&offset=1").get_json()
    assert [r["id"] for r in page] == [ids[1], ids[0]]
    assert client.get("/plant-health-records/assessments?limit=2&offset=5").get_json() == []

    middle_created = everything[1]["created_at"]
    since = client.get(f"/plant-health-records/assessments?since={middle_created}").get_json()
    assert set(r["id"] for r in since) >= {ids[1], ids[2]} and ids[0] not in [r["id"] for r in since] or len(since) == 3
    assert client.get("/plant-health-records/assessments?since=yesterday").status_code == 400


def test_regenerate_keeps_the_original_and_adds_a_new_record(client, fake_ai):
    original = make_assessment(client)
    repeat = client.post(f"/plant-health-records/assessments/{original['id']}/regenerate")
    assert repeat.status_code == 201
    assert repeat.get_json()["id"] != original["id"]
    assert client.get(f"/plant-health-records/assessments/{original['id']}").status_code == 200
    assert len(client.get("/plant-health-records/assessments").get_json()) == 2
    assert client.post("/plant-health-records/assessments/999/regenerate").status_code == 404


def test_htmx_requests_get_fragments(client):
    response = client.post(
        "/plant-health-records/assessments",
        data={"plant_ref": "Chilli", "description": "Curling leaves"},
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "<article" in html and "Reduce watering" in html and "View full record" in html

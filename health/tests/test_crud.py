"""CRUD coverage for the Plant Health service (with a fake, offline AI client)."""

from extensions import db
from models import Assessment


def test_create_assessment_from_a_description(client, app):
    response = client.post(
        "/plant-health-records/assessments",
        json={"plant_ref": "Tomato — north bed", "description": "Lower leaves yellowing."},
    )
    assert response.status_code == 201
    body = response.get_json()
    assert body["status"] == "at_risk"
    assert body["plant_ref"] == "Tomato — north bed"
    with app.app_context():
        assert Assessment.query.count() == 1


def test_create_requires_description_or_image(client):
    response = client.post("/plant-health-records/assessments", json={"plant_ref": "Basil"})
    assert response.status_code == 400


def test_read_list_and_detail(client, app):
    client.post(
        "/plant-health-records/assessments",
        json={"description": "Powdery white coating on zucchini leaves."},
    )
    with app.app_context():
        assessment_id = Assessment.query.one().id

    listing = client.get("/plant-health-records/assessments")
    assert listing.status_code == 200
    assert len(listing.get_json()) == 1

    single = client.get(f"/plant-health-records/assessments/{assessment_id}")
    assert single.status_code == 200
    assert single.get_json()["id"] == assessment_id

    page = client.get(f"/plant-health-records/{assessment_id}")
    assert page.status_code == 200
    assert b"What was submitted" in page.data


def test_update_via_json_patch(client, app):
    client.post("/plant-health-records/assessments", json={"description": "Leggy basil."})
    with app.app_context():
        assessment_id = Assessment.query.one().id

    response = client.patch(
        f"/plant-health-records/assessments/{assessment_id}",
        json={"plant_ref": "Basil (Genovese)", "notes": "Pinched out the tips; recovering."},
    )
    assert response.status_code == 200
    with app.app_context():
        updated = db.session.get(Assessment, assessment_id)
        assert updated.plant_ref == "Basil (Genovese)"
        assert updated.notes == "Pinched out the tips; recovering."
        # the AI result is untouched
        assert updated.status == "at_risk"


def test_update_via_browser_form(client, app):
    client.post("/plant-health-records/assessments", json={"description": "Carrot seedlings pale."})
    with app.app_context():
        assessment_id = Assessment.query.one().id

    response = client.post(
        f"/plant-health-records/assessments/{assessment_id}/edit",
        data={"plant_ref": "Carrot row", "description": "Carrot seedlings pale.", "notes": "Kept the surface moist."},
        follow_redirects=False,
    )
    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(Assessment, assessment_id).notes == "Kept the surface moist."


def test_update_missing_assessment_is_404(client):
    assert client.patch("/plant-health-records/assessments/999", json={"notes": "x"}).status_code == 404


def test_delete_via_api_and_form(client, app):
    for _ in range(2):
        client.post("/plant-health-records/assessments", json={"description": "leaf spot"})
    with app.app_context():
        ids = [a.id for a in Assessment.query.order_by(Assessment.id).all()]

    assert client.delete(f"/plant-health-records/assessments/{ids[0]}").status_code == 204
    form_delete = client.post(
        f"/plant-health-records/assessments/{ids[1]}/delete", follow_redirects=False
    )
    assert form_delete.status_code == 302
    with app.app_context():
        assert Assessment.query.count() == 0


def test_seed_data_gives_at_least_ten_records(seeded, app):
    assert seeded >= 10
    with app.app_context():
        assert Assessment.query.count() >= 10
        # a mix of verdicts, and the "unknown" one has a null score
        statuses = {a.status for a in Assessment.query.all()}
        assert {"healthy", "at_risk", "unhealthy", "unknown"} <= statuses


def test_healthz_reports_ai_reachability(client):
    body = client.get("/healthz").get_json()
    assert body["service"] == "health-monitoring-service"
    assert body["ai"]["reachable"] is True

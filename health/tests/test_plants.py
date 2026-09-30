"""Plant names: offered on the form, registered on first use, managed on their own page."""

from __future__ import annotations

from conftest import make_assessment

PLANTS = "/plant-health-records/plants"


def _names(client):
    return [p["name"] for p in client.get(PLANTS, headers={"Accept": "application/json"}).get_json()]


def test_a_new_plant_ref_becomes_a_title_once(client):
    assert _names(client) == []

    make_assessment(client, plant_ref="Tomato, back bed")
    make_assessment(client, plant_ref="tomato, BACK bed")  # same plant, different case
    make_assessment(client, plant_ref="Basil")
    make_assessment(client, plant_ref=None, description="Unnamed plant, wilting")

    assert _names(client) == ["Basil", "Tomato, back bed"]  # alphabetical, first spelling kept
    tomato = next(p for p in client.get(PLANTS).get_json() if p["name"] == "Tomato, back bed")
    assert tomato["assessments"] == 2


def test_form_offers_previous_titles_and_an_other_new_plant_option(client):
    make_assessment(client, plant_ref="Chilli")
    html = client.get("/plant-health-records/").get_data(as_text=True)
    assert 'data-role="plant-choice"' in html
    assert '<option value="Chilli">Chilli</option>' in html
    assert 'value="__new__"' in html and "Other / new plant" in html
    assert "Manage plant names" in html


def test_form_submission_with_a_new_name_registers_it(client):
    # The form sends the typed name as plant_ref (the select is unnamed when "new" is chosen).
    response = client.post(
        "/plant-health-records/assessments",
        data={"plant_ref": "Mint", "description": "Leggy"},
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 200
    assert _names(client) == ["Mint"]


def test_editing_a_record_registers_the_corrected_name(client):
    record = make_assessment(client, plant_ref="Tomatoe")
    client.patch(f"/plant-health-records/assessments/{record['id']}", json={"plant_ref": "Tomato"})
    assert _names(client) == ["Tomato", "Tomatoe"]

    fragment = client.patch(
        f"/plant-health-records/assessments/{record['id']}",
        data={"plant_ref": "Tomato"},
        headers={"HX-Request": "true"},
    )
    assert fragment.status_code == 200
    assert 'list="plant-names"' in fragment.get_data(as_text=True)
    assert '<option value="Tomatoe">' in fragment.get_data(as_text=True)


def test_plants_api_create_and_validation(client):
    created = client.post(PLANTS, json={"name": "  Rosemary  "})
    assert created.status_code == 201 and created.get_json()["name"] == "Rosemary"
    assert created.get_json()["assessments"] == 0

    again = client.post(PLANTS, json={"name": "rosemary"})
    assert again.status_code == 200 and again.get_json()["id"] == created.get_json()["id"]
    assert _names(client) == ["Rosemary"]

    assert client.post(PLANTS, json={}).status_code == 400
    assert client.post(PLANTS, json={"name": "   "}).status_code == 400
    assert client.post(PLANTS, json={"name": "x" * 201}).status_code == 400
    assert client.post(PLANTS, json={"name": 5}).status_code == 400


def test_deleting_a_title_keeps_its_assessments(client):
    record = make_assessment(client, plant_ref="Basil")
    plant = client.get(PLANTS).get_json()[0]

    deleted = client.delete(f"{PLANTS}/{plant['id']}")
    assert deleted.status_code == 204
    assert _names(client) == []
    assert client.delete(f"{PLANTS}/{plant['id']}").status_code == 404

    kept = client.get(f"/plant-health-records/assessments/{record['id']}").get_json()
    assert kept["plant_ref"] == "Basil"
    page = client.get(f"/plant-health-records/{record['id']}")
    assert page.status_code == 200 and b"Basil" in page.data

    # Using the name again simply re-registers it.
    make_assessment(client, plant_ref="Basil")
    assert _names(client) == ["Basil"]


def test_management_page_lists_counts_and_supports_htmx(client):
    make_assessment(client, plant_ref="Tomato")
    make_assessment(client, plant_ref="Tomato")
    make_assessment(client, plant_ref="Basil")

    page = client.get(PLANTS, headers={"Accept": "text/html,application/xhtml+xml,*/*;q=0.8"})
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert "Plant names" in html and 'data-plant-count="2"' in html
    assert "2 assessments" in html and "1 assessment" in html and "1 assessments" not in html
    assert "Remove the plant name Tomato" in html

    added = client.post(PLANTS, data={"name": "Chilli"}, headers={"HX-Request": "true"})
    assert added.status_code == 200
    assert 'data-plant-count="3"' in added.get_data(as_text=True)

    chilli = next(p for p in client.get(PLANTS).get_json() if p["name"] == "Chilli")
    removed = client.delete(f"{PLANTS}/{chilli['id']}", headers={"HX-Request": "true"})
    assert removed.status_code == 200 and removed.data == b""
    assert _names(client) == ["Basil", "Tomato"]

    empty = client.get(PLANTS, headers={"Accept": "text/html"})
    assert 'data-plant-count="0"' not in empty.get_data(as_text=True)

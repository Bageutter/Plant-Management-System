"""Public catalogue boundaries reused from the earlier Almanac MCP work."""
import json
import pytest
from app import create_app
from extensions import db
from models import AIChatMessage, Disease, Pest, PlantReference

@pytest.fixture
def catalogue(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'catalogue.db'}",
            "PLANT_IMAGE_FOLDER": str(tmp_path / "images"),
        }
    )
    with app.app_context():
        aphids = Pest(name="Aphids", description="Sap-feeding insects.")
        slugs = Pest(name="Slugs and snails", description="Leaf damage.")
        mildew = Disease(name="Powdery mildew", description="White powder on leaves.")
        for slug in ("lettuce", "tomato"):
            plant = PlantReference.query.filter_by(slug=slug).one()
            plant.pests.append(aphids)
            plant.diseases.append(mildew)
        db.session.add(slugs)
        db.session.add(
            AIChatMessage(owner_key="user:999", role="user", content="PRIVATE_CHAT_SENTINEL")
        )
        db.session.commit()
        yield app


def test_public_catalogue_search_pages_and_literal_search(catalogue):
    client = catalogue.test_client()
    first = client.get("/api/catalogue?limit=2").json
    second = client.get("/api/catalogue?limit=2&offset=2").json
    assert first["next_offset"] == 2
    assert not {x["uri"] for x in first["items"]} & {x["uri"] for x in second["items"]}
    assert (
        first["total"] == PlantReference.query.count() + Pest.query.count() + Disease.query.count()
    )
    assert client.get("/api/catalogue?q=APHIDS&kind=pest").json["items"][0]["name"] == "Aphids"
    assert client.get("/api/catalogue?q=Solanum%20lycopersicum").json["total"] >= 1
    for query in ["%", "_", "' OR 1=1 --", "no-such-plant"]:
        assert client.get("/api/catalogue", query_string={"q": query}).json["items"] == []
    for query in ["limit=0", "limit=51", "offset=-1", "limit=no", "kind=users", "q=" + "a" * 121]:
        response = client.get("/api/catalogue?" + query)
        assert response.status_code == 400
        assert response.json["error"]
    # Prefixes survive when the API is called through the shared reverse proxy.
    proxied = client.get("/api/catalogue?q=Aphids", headers={"X-Forwarded-Prefix": "/almanac"})
    assert proxied.json["items"][0]["path"].startswith("/almanac/pests/")


def test_public_details_preserve_evidence_and_make_no_writes(catalogue):
    client = catalogue.test_client()
    before = [p.to_dict() for p in PlantReference.query.order_by(PlantReference.id)]
    payload = client.get("/api/catalogue/plant/lettuce").json
    assert payload["pests"] and payload["diseases"]
    assert payload["evidence_note"]
    aphids = Pest.query.filter_by(name="Aphids").one()
    guide = client.get(f"/api/catalogue/pest/{aphids.id}?limit=1").json
    assert guide["guide_available"] and guide["guide"]["sources"]
    assert len(guide["plants"]) == 1 and guide["next_offset"] == 1
    mildew = Disease.query.filter_by(name="Powdery mildew").one()
    assert client.get(f"/api/catalogue/disease/{mildew.id}").json["guide"]["spray_note"]
    slugs = Pest.query.filter_by(name="Slugs and snails").one()
    assert client.get(f"/api/catalogue/pest/{slugs.id}").json["guide_available"] is False
    for path in ["plant/no-such-plant", "pest/999999", "disease/999999"]:
        response = client.get("/api/catalogue/" + path)
        assert response.status_code == 404 and response.json["error"]
    assert "plants_per_m2" not in payload["record"]
    assert (
        client.get("/api/catalogue/plant/lettuce/calculate?amount=10&unit=head").status_code == 404
    )
    for method in [client.post, client.put, client.patch, client.delete]:
        assert method("/api/catalogue/plant/lettuce").status_code in (400, 405)
    assert [p.to_dict() for p in PlantReference.query.order_by(PlantReference.id)] == before
    assert "PRIVATE_CHAT_SENTINEL" not in json.dumps([payload, guide])


def test_catalogue_tolerates_close_disease_name_typos(catalogue):
    client = catalogue.test_client()
    for query in ("powdery mildew", "powedery mildew", "powedery mildrew"):
        result = client.get("/api/catalogue", query_string={"q": query, "kind": "disease"}).json
        assert [item["name"] for item in result["items"]] == ["Powdery mildew"]
    assert client.get("/api/catalogue?q=Neptune").json["items"] == []

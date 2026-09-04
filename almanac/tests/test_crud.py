import os
import tempfile
import unittest

from app import create_app
from models import PlantingMonth, PlantReference
from seed_data import PLANT_REFERENCES

SEED_COUNT = len(PLANT_REFERENCES)


class FakeAuthClient:
    def __init__(self, user=None):
        self.user = user

    def current_user(self, _cookie_header):
        return self.user


class AlmanacCrudTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app(
            {
                "TESTING": True,
                "WTF_CSRF_ENABLED": False,
                "SQLALCHEMY_DATABASE_URI": f"sqlite:///{os.path.join(self.tmp.name, 'a.db')}",
                "AUTH_PUBLIC_URL": "http://auth.test",
            }
        )
        self.auth = FakeAuthClient({"id": 1, "email": "amy@example.com"})
        self.app.extensions["auth_client"] = self.auth
        self.client = self.app.test_client()

    def tearDown(self):
        self.tmp.cleanup()

    # -- create -------------------------------------------------------------

    def test_logged_out_user_cannot_reach_the_new_form(self):
        self.auth.user = None
        response = self.client.get("/plants/new", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "http://auth.test/login")

    def test_create_plant_from_the_form(self):
        response = self.client.post(
            "/plants",
            data={
                "common_name": "Tarragon",
                "scientific_name": "Artemisia dracunculus",
                "family": "Asteraceae",
                "summary": "A perennial culinary herb.",
                "months": ["3", "4", "9"],
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Tarragon", response.data)
        with self.app.app_context():
            plant = PlantReference.query.filter_by(slug="tarragon").one()
            self.assertEqual(plant.scientific_name, "Artemisia dracunculus")
            self.assertEqual(
                sorted(m.month_number for m in plant.planting_months), [3, 4, 9]
            )

    def test_create_plant_requires_a_common_and_scientific_name(self):
        response = self.client.post("/plants", data={"common_name": "  "})
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"Common name is required", response.data)
        with self.app.app_context():
            self.assertEqual(PlantReference.query.count(), SEED_COUNT)  # only the seed data

    def test_slug_collisions_get_a_suffix(self):
        for _ in range(2):
            self.client.post(
                "/plants",
                data={"common_name": "Tomato", "scientific_name": "Solanum lycopersicum x"},
            )
        with self.app.app_context():
            slugs = {p.slug for p in PlantReference.query.filter(
                PlantReference.common_name == "Tomato"
            )}
            self.assertEqual(slugs, {"tomato", "tomato-2", "tomato-3"})  # "tomato" is seeded

    def test_rejects_out_of_range_months(self):
        response = self.client.post(
            "/plants",
            data={"common_name": "X", "scientific_name": "X x", "months": ["13"]},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"between 1 and 12", response.data)

    # -- update -------------------------------------------------------------

    def test_edit_plant_updates_fields_and_months(self):
        self.client.post(
            "/plants",
            data={"common_name": "Sage", "scientific_name": "Salvia officinalis", "months": ["4"]},
        )
        response = self.client.post(
            "/plants/sage/edit",
            data={
                "common_name": "Common Sage",
                "scientific_name": "Salvia officinalis",
                "family": "Lamiaceae",
                "summary": "Updated.",
                "months": ["4", "5"],
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            plant = PlantReference.query.filter_by(slug="sage").one()  # slug is stable
            self.assertEqual(plant.common_name, "Common Sage")
            self.assertEqual(plant.summary, "Updated.")
            self.assertEqual(sorted(m.month_number for m in plant.planting_months), [4, 5])

    def test_edit_missing_plant_is_404(self):
        self.assertEqual(self.client.get("/plants/nope/edit").status_code, 404)

    # -- delete -----------------------------------------------------------

    def test_delete_plant_removes_it_and_its_months(self):
        self.client.post(
            "/plants",
            data={
                "common_name": "Dill",
                "scientific_name": "Anethum graveolens",
                "months": ["7", "8", "9"],
            },
        )
        with self.app.app_context():
            before = PlantingMonth.query.count()

        response = self.client.post("/plants/dill/delete", follow_redirects=True)

        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            self.assertIsNone(PlantReference.query.filter_by(slug="dill").first())
            self.assertEqual(PlantingMonth.query.count(), before - 3)  # cascade

    def test_delete_requires_login(self):
        self.auth.user = None
        response = self.client.post("/plants/tomato/delete", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            self.assertIsNotNone(PlantReference.query.filter_by(slug="tomato").first())

    # -- API --------------------------------------------------------------

    def test_api_crud_round_trip(self):
        created = self.client.post(
            "/api/plants",
            json={"common_name": "Thyme", "scientific_name": "Thymus vulgaris", "months": [4, 5]},
        )
        self.assertEqual(created.status_code, 201)
        body = created.get_json()
        self.assertEqual(body["slug"], "thyme")
        self.assertEqual(body["planting_months"], ["April", "May"])

        updated = self.client.put(
            "/api/plants/thyme",
            json={"common_name": "Common Thyme", "scientific_name": "Thymus vulgaris", "months": [5]},
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.get_json()["common_name"], "Common Thyme")

        self.assertEqual(self.client.delete("/api/plants/thyme").status_code, 204)
        self.assertEqual(self.client.get("/api/plants/thyme").status_code, 404)

    def test_api_write_requires_login(self):
        self.auth.user = None
        response = self.client.post("/api/plants", json={"common_name": "X", "scientific_name": "Y"})
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()

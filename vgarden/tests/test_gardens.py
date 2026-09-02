import os
import tempfile
import unittest

from app import create_app
from extensions import db
from models import Garden


class VGardenTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = os.path.join(self.temp_dir.name, "vgarden.db")

        class TestConfig:
            TESTING = True
            SQLALCHEMY_DATABASE_URI = f"sqlite:///{database_path}"
            SQLALCHEMY_TRACK_MODIFICATIONS = False
            AUTH_PUBLIC_URL = "http://auth.test"
            HEALTH_PUBLIC_URL = "http://health.test/"
            ALMANAC_PUBLIC_URL = "http://almanac.test/"

        self.app = create_app(TestConfig)
        self.client = self.app.test_client()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
        self.temp_dir.cleanup()

    def _create(self, **payload):
        return self.client.post("/gardens", json=payload)

    def test_create_garden_returns_the_new_record(self):
        response = self._create(owner_id=7, name="  Back terrace  ")

        self.assertEqual(response.status_code, 201)
        body = response.get_json()
        self.assertEqual(body["owner_id"], 7)
        self.assertEqual(body["name"], "Back terrace")
        self.assertIn("id", body)
        self.assertIn("created_at", body)

        with self.app.app_context():
            self.assertEqual(Garden.query.count(), 1)

    def test_create_garden_requires_integer_owner_id(self):
        response = self._create(owner_id="7", name="Terrace")

        self.assertEqual(response.status_code, 400)
        self.assertIn("owner_id", response.get_json()["error"])

    def test_create_garden_requires_a_non_empty_name(self):
        response = self._create(owner_id=1, name="   ")

        self.assertEqual(response.status_code, 400)
        self.assertIn("name", response.get_json()["error"])

    def test_create_garden_rejects_an_overly_long_name(self):
        response = self._create(owner_id=1, name="x" * 121)

        self.assertEqual(response.status_code, 400)
        self.assertIn("120 characters", response.get_json()["error"])

    def test_list_gardens_can_filter_by_owner(self):
        self._create(owner_id=1, name="Mine")
        self._create(owner_id=2, name="Theirs")

        everything = self.client.get("/gardens").get_json()
        just_owner_one = self.client.get("/gardens?owner_id=1").get_json()

        self.assertEqual(len(everything), 2)
        self.assertEqual([g["name"] for g in just_owner_one], ["Mine"])

    def test_get_garden_returns_404_when_missing(self):
        response = self.client.get("/gardens/999")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.get_json()["error"], "garden not found")

    def test_delete_garden_removes_the_record(self):
        garden_id = self._create(owner_id=1, name="Doomed").get_json()["id"]

        deleted = self.client.delete(f"/gardens/{garden_id}")
        missing_now = self.client.get(f"/gardens/{garden_id}")

        self.assertEqual(deleted.status_code, 204)
        self.assertEqual(missing_now.status_code, 404)

    def test_delete_garden_returns_404_when_missing(self):
        self.assertEqual(self.client.delete("/gardens/999").status_code, 404)

    def test_view_garden_renders_the_page(self):
        garden_id = self._create(owner_id=1, name="Sunny bed").get_json()["id"]

        response = self.client.get(f"/gardens/{garden_id}/view")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Sunny bed", response.data)
        # header partial is pulled from shared/templates
        self.assertIn(b"Plant Management System", response.data)

    def test_view_missing_garden_returns_the_not_found_page(self):
        response = self.client.get("/gardens/999/view")

        self.assertEqual(response.status_code, 404)
        self.assertIn(b"Garden not found", response.data)


if __name__ == "__main__":
    unittest.main()

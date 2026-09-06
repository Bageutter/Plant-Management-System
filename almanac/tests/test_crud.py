import base64
import io
import os
import tempfile
import unittest

from app import create_app
from models import PlantImage, PlantingMonth, PlantReference


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


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
                "PLANT_IMAGE_FOLDER": os.path.join(self.tmp.name, "plant_images"),
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
                "common_name": "Rosemary",
                "scientific_name": "Salvia rosmarinus",
                "family": "Lamiaceae",
                "summary": "A woody perennial herb.",
                "months": ["3", "4", "9"],
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Rosemary", response.data)
        with self.app.app_context():
            plant = PlantReference.query.filter_by(slug="rosemary").one()
            self.assertEqual(plant.scientific_name, "Salvia rosmarinus")
            self.assertEqual(
                sorted(m.month_number for m in plant.planting_months), [3, 4, 9]
            )

    def test_image_picker_supports_choose_drop_and_paste(self):
        response = self.client.get("/plants/new")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'id="plant-image-paste-zone"', response.data)
        self.assertIn(b"Choose, drop, or paste an image", response.data)
        self.assertIn(b"clipboardData", response.data)
        self.assertIn(b"DataTransfer", response.data)
        self.assertIn(b"createImageBitmap", response.data)
        self.assertIn(b"canvas.toBlob", response.data)
        self.assertIn(b"compressed automatically", response.data)

    def test_create_plant_with_an_image(self):
        response = self.client.post(
            "/plants",
            data={
                "common_name": "Rosemary",
                "scientific_name": "Salvia rosmarinus",
                "image": (io.BytesIO(PNG_1X1), "rosemary.png"),
            },
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"/plant-images/", response.data)
        with self.app.app_context():
            image = PlantImage.query.one()
            filename = image.filename
            self.assertEqual(image.content_type, "image/png")
            self.assertTrue(os.path.isfile(os.path.join(self.tmp.name, "plant_images", filename)))

        served = self.client.get(f"/plant-images/{filename}")
        self.assertEqual(served.status_code, 200)
        self.assertEqual(served.mimetype, "image/png")
        self.assertEqual(served.data, PNG_1X1)
        self.assertTrue(self.client.get("/api/plants/rosemary").get_json()["image_url"].endswith(filename))

    def test_rejects_invalid_and_oversized_images(self):
        invalid = self.client.post(
            "/plants",
            data={
                "common_name": "Unsafe",
                "scientific_name": "Invalid file",
                "image": (io.BytesIO(b"not an image"), "unsafe.svg"),
            },
        )
        self.assertEqual(invalid.status_code, 400)
        self.assertIn(b"JPEG, PNG, GIF, or WebP", invalid.data)

        oversized = self.client.post(
            "/plants",
            data={
                "common_name": "Large",
                "scientific_name": "Large file",
                "image": (io.BytesIO(PNG_1X1 + b"x" * (5 * 1024 * 1024)), "large.png"),
            },
        )
        self.assertEqual(oversized.status_code, 400)
        self.assertIn(b"5 MB or smaller", oversized.data)
        with self.app.app_context():
            self.assertIsNone(PlantReference.query.filter_by(slug="unsafe").first())
            self.assertIsNone(PlantReference.query.filter_by(slug="large").first())

    def test_edit_can_replace_and_remove_an_image(self):
        self.client.post(
            "/plants",
            data={
                "common_name": "Sage",
                "scientific_name": "Salvia officinalis",
                "image": (io.BytesIO(PNG_1X1), "sage.png"),
            },
        )
        with self.app.app_context():
            original = PlantReference.query.filter_by(slug="sage").one().image.filename

        replacement = b"GIF89a" + b"replacement"
        page = self.client.post(
            "/plants/sage/edit",
            data={
                "common_name": "Sage",
                "scientific_name": "Salvia officinalis",
                "image": (io.BytesIO(replacement), "sage.gif"),
            },
            follow_redirects=True,
        )
        self.assertIn(b"/plant-images/", page.data)
        with self.app.app_context():
            current = PlantReference.query.filter_by(slug="sage").one().image.filename
            self.assertNotEqual(current, original)
            self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "plant_images", original)))
            self.assertTrue(os.path.exists(os.path.join(self.tmp.name, "plant_images", current)))

        edit_page = self.client.get("/plants/sage/edit")
        self.assertIn(b"Remove current image", edit_page.data)
        self.client.post(
            "/plants/sage/edit",
            data={
                "common_name": "Sage",
                "scientific_name": "Salvia officinalis",
                "remove_image": "1",
            },
        )
        with self.app.app_context():
            self.assertIsNone(PlantReference.query.filter_by(slug="sage").one().image)
            self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "plant_images", current)))

    def test_create_plant_requires_a_common_and_scientific_name(self):
        response = self.client.post("/plants", data={"common_name": "  "})
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"Common name is required", response.data)
        with self.app.app_context():
            self.assertEqual(PlantReference.query.count(), 6)  # only the seed data

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
                "image": (io.BytesIO(PNG_1X1), "dill.png"),
            },
        )
        with self.app.app_context():
            before = PlantingMonth.query.count()
            image_filename = PlantReference.query.filter_by(slug="dill").one().image.filename

        response = self.client.post("/plants/dill/delete", follow_redirects=True)

        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            self.assertIsNone(PlantReference.query.filter_by(slug="dill").first())
            self.assertEqual(PlantingMonth.query.count(), before - 3)  # cascade
            self.assertFalse(
                os.path.exists(os.path.join(self.tmp.name, "plant_images", image_filename))
            )

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

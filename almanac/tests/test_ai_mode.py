import os
import tempfile
import unittest

from ai import AIUnavailableError
from app import create_app
from extensions import db
from models import AIChatMessage


class FakeAlmanacAI:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def ask(self, question, plants):
        self.calls.append({"question": question, "plants": plants})
        if self.error:
            raise self.error
        return self.response


class FakeAuthClient:
    def __init__(self, user=None):
        self.user = user

    def current_user(self, _cookie_header):
        return self.user


class AlmanacAIModeTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = os.path.join(self.temp_dir.name, "almanac.db")
        self.app = create_app(
            {
                "TESTING": True,
                "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path}",
            }
        )
        self.auth = FakeAuthClient({"id": 1, "email": "amy@example.com"})
        self.app.extensions["auth_client"] = self.auth
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_ai_mode_renders_on_almanac_page(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Ask the Almanac", response.data)
        self.assertIn(b"ai-chat-launcher", response.data)
        self.assertIn(b"ai-chat-panel", response.data)
        self.assertNotIn(b"Local AI", response.data)
        self.assertIn(b"pendingQuestion", response.data)

    def test_existing_plant_api_still_lists_every_record(self):
        response = self.client.get("/api/plants")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["count"], 6)

    def test_logged_out_user_sees_login_link_and_cannot_use_chat(self):
        self.auth.user = None

        page = self.client.get("/")
        response = self.client.post("/ai/ask", data={"question": "Tell me about basil"})

        self.assertIn(b"Log in to ask the Almanac", page.data)
        self.assertNotIn(b'id="ai-chat-panel"', page.data)
        self.assertEqual(response.status_code, 401)

    def test_ai_question_uses_seeded_almanac_records(self):
        fake = FakeAlmanacAI(
            {
                "answer": "Tomatoes are listed for January and September to December.",
                "sources": ["tomato"],
            }
        )
        self.app.extensions["almanac_ai"] = fake

        response = self.client.post(
            "/ai/ask", data={"question": "When should I plant tomatoes?"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"January and September to December", response.data)
        self.assertIn(b"Tomato", response.data)
        self.assertEqual(fake.calls[0]["question"], "When should I plant tomatoes?")
        self.assertEqual(len(fake.calls[0]["plants"]), 1)
        self.assertEqual(fake.calls[0]["plants"][0]["slug"], "tomato")

        page = self.client.get("/")
        self.assertIn(b"When should I plant tomatoes?", page.data)
        self.assertIn(b"January and September to December", page.data)
        self.assertIn(b'href="/plants/tomato"', page.data)

        with self.app.app_context():
            self.assertEqual(AIChatMessage.query.count(), 2)

    def test_ai_question_rejects_empty_input(self):
        response = self.client.post("/ai/ask", data={"question": "   "})

        self.assertEqual(response.status_code, 400)
        self.assertIn(b"Enter a question", response.data)

    def test_ai_question_reports_local_model_failure(self):
        self.app.extensions["almanac_ai"] = FakeAlmanacAI(
            error=AIUnavailableError("Ollama is unavailable")
        )

        response = self.client.post(
            "/ai/ask", data={"question": "What can I plant this month?"}
        )

        self.assertEqual(response.status_code, 503)
        self.assertIn(b"local AI model is unavailable", response.data)

        with self.app.app_context():
            self.assertEqual(AIChatMessage.query.count(), 0)

    def test_ai_answer_is_escaped_and_unknown_sources_are_ignored(self):
        self.app.extensions["almanac_ai"] = FakeAlmanacAI(
            {
                "answer": "<script>alert('unsafe')</script>",
                "sources": ["tomato", "not-a-real-plant"],
            }
        )

        response = self.client.post("/ai/ask", data={"question": "Tell me about tomato"})

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"<script>", response.data)
        self.assertIn(b"&lt;script&gt;", response.data)
        self.assertIn(b"Tomato", response.data)
        self.assertNotIn(b"not-a-real-plant", response.data)

    def test_chat_history_belongs_to_the_authenticated_user(self):
        self.app.extensions["almanac_ai"] = FakeAlmanacAI(
            {"answer": "Tomato answer", "sources": ["tomato"]}
        )
        self.client.post("/ai/ask", data={"question": "Tell me about tomato"})

        self.auth.user = {"id": 2, "email": "other@example.com"}
        response = self.client.get("/")

        self.assertNotIn(b"Tomato answer", response.data)

    def test_clear_chat_removes_only_current_user_history(self):
        self.app.extensions["almanac_ai"] = FakeAlmanacAI(
            {"answer": "Tomato answer", "sources": ["tomato"]}
        )
        self.client.post("/ai/ask", data={"question": "Tell me about tomato"})
        self.auth.user = {"id": 2, "email": "other@example.com"}
        self.client.post("/ai/ask", data={"question": "Tell me about tomato"})
        self.auth.user = {"id": 1, "email": "amy@example.com"}

        response = self.client.post("/ai/clear")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"Tomato answer", response.data)
        with self.app.app_context():
            remaining = db.session.query(AIChatMessage).all()
            self.assertEqual(len(remaining), 2)
            self.assertTrue(all(message.owner_key == "user:2" for message in remaining))


if __name__ == "__main__":
    unittest.main()

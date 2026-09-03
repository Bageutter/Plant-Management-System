import os
import tempfile
import unittest

from ai import AIUnavailableError
from app import create_app
from extensions import db
from models import AIChatMessage, AILoopRun


class FakeAlmanacAI:
    """Stand-in drafter. `.draft(question, grounding, feedback)` is the loop's ACT step."""

    def __init__(self, answer="An answer.", error=None):
        self.answer = answer
        self.error = error
        self.calls = []

    def draft(self, question, grounding, feedback=None):
        self.calls.append({"question": question, "grounding": grounding, "feedback": feedback})
        if self.error:
            raise self.error
        return self.answer


class FakeReviewer:
    """Emits verdicts from `script`, repeating the last one."""

    def __init__(self, script=None):
        self.script = list(script or ["approved"])
        self.calls = []

    def review(self, question, grounding, draft):
        self.calls.append(draft)
        verdict = self.script[min(len(self.calls) - 1, len(self.script) - 1)]
        if verdict == "approved":
            return {"verdict": "approved", "issues": [], "guidance": ""}
        return {"verdict": "revise", "issues": ["ungrounded"], "guidance": f"fix {len(self.calls)}"}


class FakeAuthClient:
    def __init__(self, user=None):
        self.user = user

    def current_user(self, _cookie_header):
        return self.user


class AlmanacAIModeTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.app = create_app(
            {
                "TESTING": True,
                "WTF_CSRF_ENABLED": False,
                "SQLALCHEMY_DATABASE_URI": f"sqlite:///{os.path.join(self.temp_dir.name, 'a.db')}",
                "AI_LOOP_LOG_DIR": os.path.join(self.temp_dir.name, "ai-loop-logs"),
                "AI_LOOP_MAX_ITERATIONS": 2,
            }
        )
        self.auth = FakeAuthClient({"id": 1, "email": "amy@example.com"})
        self.app.extensions["auth_client"] = self.auth
        self.reviewer = FakeReviewer()
        self.app.extensions["ai_loop_reviewer"] = self.reviewer
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp_dir.cleanup()

    def _set_ai(self, ai):
        self.app.extensions["almanac_ai"] = ai
        return ai

    def test_ai_mode_renders_on_almanac_page(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Ask the Almanac", response.data)
        self.assertIn(b"ai-chat-launcher", response.data)
        self.assertIn(b"ai-chat-panel", response.data)
        self.assertIn(b"ai-chat-resizer", response.data)
        self.assertIn(b"Resize Almanac chat", response.data)
        self.assertIn(b"almanac-chat-width", response.data)
        self.assertIn(b"pendingQuestion", response.data)

    def test_existing_plant_api_still_lists_every_record(self):
        self.assertEqual(self.client.get("/api/plants").get_json()["count"], 6)

    def test_logged_out_user_cannot_use_chat(self):
        self.auth.user = None

        page = self.client.get("/")
        response = self.client.post("/ai/ask", data={"question": "Tell me about basil"})

        self.assertIn(b"Log in to ask the Almanac", page.data)
        self.assertEqual(response.status_code, 401)

    def test_ai_question_runs_the_loop_and_records_it(self):
        fake = self._set_ai(
            FakeAlmanacAI("Tomatoes are listed for January and September to December.")
        )

        response = self.client.post(
            "/ai/ask", data={"question": "When should I plant tomatoes?"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"January and September to December", response.data)
        self.assertIn(b"Plan \xe2\x86\x92 Act \xe2\x86\x92 Observe \xe2\x86\x92 Adapt", response.data)
        self.assertIn(b"How this answer was checked", response.data)
        self.assertIn(b"Plan \xc2\xb7 Evidence selected", response.data)
        self.assertIn(b"1 plant record", response.data)
        self.assertIn(b"Observe 1 \xc2\xb7 Independent review", response.data)
        self.assertIn(b"Reviewer approved this draft", response.data)
        self.assertIn(b"Answer accepted after validation", response.data)
        self.assertIn(b"Open detailed validation report", response.data)

        call = fake.calls[0]
        self.assertEqual(call["question"], "When should I plant tomatoes?")
        self.assertEqual(call["feedback"], None)
        self.assertEqual([p["slug"] for p in call["grounding"]["plant_records"]], ["tomato"])

        page = self.client.get("/")
        self.assertIn(b"When should I plant tomatoes?", page.data)
        self.assertIn(b'href="/plants/tomato"', page.data)  # source derived from the answer text

        with self.app.app_context():
            self.assertEqual(AIChatMessage.query.count(), 2)
            run = AILoopRun.query.one()
            self.assertEqual(run.iterations, 1)
            self.assertEqual(run.verdict, "approved")
            self.assertEqual([e["phase"] for e in run.trace], ["plan", "act", "observe", "adapt"])
            self.assertTrue(os.path.isfile(run.transcript_path))

    def test_reviewer_revision_loops_and_carries_feedback(self):
        fake = self._set_ai(FakeAlmanacAI("Basil likes warmth."))
        self.reviewer.script = ["revise", "approved"]

        self.client.post("/ai/ask", data={"question": "Tell me about basil"})

        self.assertEqual([c["feedback"] for c in fake.calls], [None, "fix 1"])
        with self.app.app_context():
            run = AILoopRun.query.one()
            self.assertEqual(run.iterations, 2)
            self.assertEqual(run.verdict, "approved")

    def test_reviewer_never_satisfied_caps_iterations(self):
        self._set_ai(FakeAlmanacAI("still off"))
        self.reviewer.script = ["revise"]

        self.client.post("/ai/ask", data={"question": "Tell me about basil"})

        with self.app.app_context():
            run = AILoopRun.query.one()
            self.assertEqual(run.iterations, 2)
            self.assertEqual(run.verdict, "revised_capped")

    def test_ai_question_rejects_empty_input(self):
        response = self.client.post("/ai/ask", data={"question": "   "})
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"Enter a question", response.data)

    def test_ai_question_reports_local_model_failure(self):
        self._set_ai(FakeAlmanacAI(error=AIUnavailableError("Ollama is unavailable")))

        response = self.client.post("/ai/ask", data={"question": "What can I plant now?"})

        self.assertEqual(response.status_code, 503)
        self.assertIn(b"local AI model is unavailable", response.data)
        with self.app.app_context():
            self.assertEqual(AIChatMessage.query.count(), 0)
            self.assertEqual(AILoopRun.query.count(), 0)

    def test_ai_answer_is_html_escaped(self):
        self._set_ai(FakeAlmanacAI("<script>alert('x')</script> about tomato"))

        response = self.client.post("/ai/ask", data={"question": "Tell me about tomato"})

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"<script>", response.data)
        self.assertIn(b"&lt;script&gt;", response.data)
        self.assertIn(b'href="/plants/tomato"', response.data)

    def test_chat_history_belongs_to_the_authenticated_user(self):
        self._set_ai(FakeAlmanacAI("Tomato answer"))
        self.client.post("/ai/ask", data={"question": "Tell me about tomato"})

        self.auth.user = {"id": 2, "email": "other@example.com"}
        self.assertNotIn(b"Tomato answer", self.client.get("/").data)

    def test_clear_chat_removes_only_current_user_history(self):
        self._set_ai(FakeAlmanacAI("Tomato answer"))
        self.client.post("/ai/ask", data={"question": "Tell me about tomato"})
        self.auth.user = {"id": 2, "email": "other@example.com"}
        self.client.post("/ai/ask", data={"question": "Tell me about tomato"})
        self.auth.user = {"id": 1, "email": "amy@example.com"}

        self.client.post("/ai/clear")

        with self.app.app_context():
            self.assertTrue(
                all(m.owner_key == "user:2" for m in db.session.query(AIChatMessage).all())
            )
            self.assertTrue(
                all(r.owner_key == "user:2" for r in db.session.query(AILoopRun).all())
            )

    def test_loop_trace_page_is_owner_scoped(self):
        self._set_ai(FakeAlmanacAI("trace me"))
        self.client.post("/ai/ask", data={"question": "Tell me about tomato"})
        with self.app.app_context():
            run_id = AILoopRun.query.one().id

        response = self.client.get(f"/ai/loop/{run_id}")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Answer validation report", response.data)
        self.assertIn(b"process summary, not private model reasoning", response.data)
        self.auth.user = {"id": 2, "email": "other@example.com"}
        self.assertEqual(self.client.get(f"/ai/loop/{run_id}").status_code, 404)


if __name__ == "__main__":
    unittest.main()

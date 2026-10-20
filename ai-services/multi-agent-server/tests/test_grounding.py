import unittest
from unittest.mock import Mock, patch

from reviewer import _review_record, review_result
from worker import select_evidence


class GroundingTests(unittest.TestCase):
    def test_named_variety_excludes_neighbouring_records(self):
        evidence = {
            "mode": "chroma",
            "passages": [
                {"title": "Tomato - Black Krim — plant reference"},
                {"title": "Tomato - Sweet 1000 — plant reference"},
                {"title": "Okra — plant reference"},
            ],
        }
        selected = select_evidence("What sunlight does Tomato - Black Krim need?", evidence)
        self.assertEqual(selected["passages"], evidence["passages"][:1])
        self.assertEqual(len(evidence["passages"]), 3)
        self.assertEqual(select_evidence("Compare tomato varieties", evidence), evidence)

    def test_missing_field_claim_is_checked_against_recorded_fields(self):
        plan = {"steps": ["Check"]}
        result = {"answer": "Sunlight not recorded."}
        missing = _review_record(plan, result, {"passages": [{"text": "Water needs: high."}]})
        self.assertEqual(missing, {"recommendation": "accept", "issues": []})
        contradiction = _review_record(
            plan, result, {"passages": [{"text": "Sun needs: full sun."}]}
        )
        self.assertEqual(contradiction["recommendation"], "revise")

    def test_single_source_does_not_need_title_repeated(self):
        with patch(
            "reviewer._review_record", return_value={"recommendation": "accept", "issues": []}
        ) as check:
            result = review_result(
                {"steps": ["Check"]},
                {
                    "answer": "Sun needs: full sun. Water needs: high.",
                    "cited_chunk_ids": ["plant:1"],
                },
                {
                    "passages": [
                        {
                            "chunk_id": "plant:1",
                            "title": "Black Krim — reference",
                            "text": "Sun needs: full sun.",
                        }
                    ]
                },
            )
        self.assertEqual(result, {"recommendation": "accept", "issues": []})
        check.assert_called_once()

    def test_reviewer_cannot_invent_a_quote(self):
        response = Mock()
        response.json.return_value = {
            "message": {"content": '{"issues":[{"quote":"invented claim","reason":"unsupported"}]}'}
        }
        with patch("reviewer.httpx.post", return_value=response):
            with self.assertRaisesRegex(ValueError, "outside the answer"):
                _review_record({"steps": ["Check"]}, {"answer": "Full sun"}, {"passages": []})


if __name__ == "__main__":
    unittest.main()

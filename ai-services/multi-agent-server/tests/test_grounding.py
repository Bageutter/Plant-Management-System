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

    def test_mangled_quote_becomes_an_issue_for_the_human_instead_of_failing_the_review(self):
        # Seen live: the reviewer quoted the answer with "30/-100" for "30/100". The record
        # is flagged for a manual check and the other citations are still reviewed.
        plan = {"steps": ["Check"]}
        result = {"answer": "Health score 30/100 at risk.", "cited_chunk_ids": ["health-1", "health-2"]}
        evidence = {"passages": [
            {"chunk_id": "health-1", "title": "Assessment 1 Tomato — Plant Health record",
             "text": "Status: at risk; health score 30/100"},
            {"chunk_id": "health-2", "title": "Assessment 2 Tomato — Plant Health record",
             "text": "Status: unknown"},
        ]}
        replies = [
            '{"issues":[{"quote":"Health score 30/-100 at risk.","reason":"unsupported"}]}',
            '{"issues":[{"quote":"health  score 30/100","reason":"score not recorded"}]}',
        ]
        response = Mock()
        response.json.side_effect = [{"message": {"content": reply}} for reply in replies]
        with patch("reviewer.httpx.post", return_value=response):
            review = review_result(plan, result, evidence)
        self.assertEqual(review["recommendation"], "revise")
        self.assertEqual(len(review["issues"]), 2)
        self.assertIn("health-1: the reviewer flagged text that is not verbatim", review["issues"][0])
        self.assertIn("30/-100", review["issues"][0])
        # Case and whitespace differences are not "outside the answer".
        self.assertEqual(review["issues"][1], "health-2: 'health  score 30/100': score not recorded")

        response.json.side_effect = None
        response.json.return_value = {"message": {"content": replies[0]}}
        with patch("reviewer.httpx.post", return_value=response):
            refusal = review_result(plan, {"answer": "Health score 30/100 at risk.", "cited_chunk_ids": []},
                                    evidence)
        self.assertEqual(refusal["recommendation"], "revise")
        self.assertIn("not verbatim", refusal["issues"][0])


if __name__ == "__main__":
    unittest.main()

import json
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


    def test_field_led_comparison_uses_sources_without_title_labels(self):
        passages = [
            {"chunk_id": "basil", "title": "Basil — plant reference", "text": "Sun needs: full sun."},
            {"chunk_id": "zucchini", "title": "Zucchini — plant reference", "text": "Sun needs: full sun."},
        ]
        result = {"answer": "Sunlight: Both basil and zucchini need full sun.",
                  "cited_chunk_ids": ["basil", "zucchini"]}
        with patch("reviewer._review_record", return_value={"recommendation": "accept", "issues": []}) as check:
            review = review_result({"steps": ["Compare"]}, result, {"passages": passages})
        self.assertEqual(review, {"recommendation": "accept", "issues": []})
        check.assert_called_once()
        self.assertFalse(check.call_args.kwargs["check_fields"])
        self.assertEqual(check.call_args.args[2]["passages"], passages)

    def test_shared_sunlight_and_ph_claims_require_each_record(self):
        passages = [
            {"chunk_id": "basil", "title": "Basil — plant reference",
             "text": "Sun needs: full sun.\nMinimum soil pH: 6.0.\nMaximum soil pH: 7.0."},
            {"chunk_id": "zucchini", "title": "Zucchini — plant reference", "text": "Summary: Summer crop."},
        ]
        result = {"answer": "Sunlight: Both plants need full sun. Soil pH: Both have a range of 6.0 to 7.0.",
                  "cited_chunk_ids": ["basil", "zucchini"]}
        with patch("reviewer._review_record", return_value={"recommendation": "accept", "issues": []}) as check:
            review = review_result({"steps": ["Compare"]}, result, {"passages": passages})
        self.assertEqual(review["recommendation"], "revise")
        self.assertTrue(any("Zucchini has no recorded sunlight" in issue for issue in review["issues"]))
        self.assertTrue(any("Zucchini has no recorded soil pH" in issue for issue in review["issues"]))
        self.assertFalse(any("unused" in issue for issue in review["issues"]))
        check.assert_called_once()

    def test_joint_review_preserves_model_findings(self):
        passages = [{"chunk_id": "a", "title": "Basil — reference", "text": "Water needs: moderate."},
                    {"chunk_id": "b", "title": "Zucchini — reference", "text": "Summary: crop."}]
        result = {"answer": "Water: Zucchini needs daily watering.", "cited_chunk_ids": ["a", "b"]}
        with patch("reviewer._review_record", return_value={"recommendation": "revise", "issues": ["Daily watering is unsupported."]}):
            review = review_result({"steps": ["Check"]}, result, {"passages": passages})
        self.assertEqual(review["recommendation"], "revise")
        self.assertIn("Daily watering is unsupported.", review["issues"])


    def test_model_cannot_flag_missing_information_as_an_unsupported_positive_claim(self):
        response = Mock()
        response.json.return_value = {"message": {"content": json.dumps({"issues": [
            {"quote": "Water needs: zucchini is not recorded", "reason": "Source does not record water needs for zucchini"}
        ]})}}
        with patch("reviewer.httpx.post", return_value=response):
            review = _review_record({"steps": ["Compare"]},
                                    {"answer": "Water needs: zucchini is not recorded"},
                                    {"passages": [{"text": "Summary: Zucchini crop."}]}, check_fields=False)
        self.assertEqual(review, {"recommendation": "accept", "issues": []})


    def test_shared_field_checks_combine_chunks_for_the_same_plant(self):
        from reviewer import _shared_claim_checks
        passages = [
            {"title": "Basil — care", "text": "Care: pinch tips."},
            {"title": "Basil — reference", "text": "Sun needs: full sun."},
            {"title": "Zucchini — reference", "text": "Sun needs: full sun."},
        ]
        self.assertEqual(_shared_claim_checks("Sunlight: Both need full sun.", passages), [])


if __name__ == "__main__":
    unittest.main()

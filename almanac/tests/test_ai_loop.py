"""Unit tests for the shared Plan -> Act -> Observe -> Adapt module
(shared/ai_loop.py), driven with fakes. No Ollama, no Flask."""

import json
import logging

import ai_loop


class FakeReviewer:
    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def review(self, question, grounding, draft):
        self.calls.append(draft)
        verdict = self.script[min(len(self.calls) - 1, len(self.script) - 1)]
        if verdict == "approved":
            return {"verdict": "approved", "issues": [], "guidance": ""}
        return {"verdict": "revise", "issues": ["ungrounded"], "guidance": f"fix {len(self.calls)}"}


def _context():
    return {"garden": {"name": "G"}, "conversation": []}, {"areas": 0, "plantings": 0}


def _loop(tmp_path, drafter, reviewer, max_iterations=3):
    return ai_loop.AgenticLoop(
        service="almanac",
        drafter=drafter,
        reviewer=reviewer,
        log_dir=str(tmp_path),
        max_iterations=max_iterations,
    )


def test_approved_first_pass(tmp_path):
    drafts = []
    loop = _loop(tmp_path, lambda q, g, fb: drafts.append(fb) or "answer", FakeReviewer(["approved"]))

    result = loop.run("q", _context)

    assert result.answer == "answer"
    assert result.iterations == 1
    assert result.verdict == "approved"
    assert drafts == [None]  # no feedback on the first act
    assert [e["phase"] for e in result.trace] == ["plan", "act", "observe", "adapt"]


def test_revision_carries_guidance_into_next_act(tmp_path):
    seen_feedback = []

    def drafter(q, g, fb):
        seen_feedback.append(fb)
        return f"draft {len(seen_feedback)}"

    result = _loop(tmp_path, drafter, FakeReviewer(["revise", "approved"])).run("q", _context)

    assert result.iterations == 2
    assert result.verdict == "approved"
    assert seen_feedback == [None, "fix 1"]
    phases = [e["phase"] for e in result.trace]
    assert phases == ["plan", "act", "observe", "adapt", "act", "observe", "adapt"]


def test_caps_at_max_iterations(tmp_path):
    result = _loop(
        tmp_path, lambda q, g, fb: "nope", FakeReviewer(["revise"]), max_iterations=2
    ).run("q", _context)

    assert result.iterations == 2
    assert result.verdict == "revised_capped"
    assert [e["phase"] for e in result.trace].count("act") == 2


def test_no_reviewer_is_single_shot_fallback(tmp_path):
    result = _loop(tmp_path, lambda q, g, fb: "solo", None).run("q", _context)

    assert result.verdict == "fallback"
    assert result.iterations == 1
    assert [e["phase"] for e in result.trace] == ["plan", "fallback"]


def test_reviewer_outage_falls_back_mid_loop(tmp_path):
    class Broken:
        def review(self, *a):
            raise ai_loop.LoopError("ollama down")

    result = _loop(tmp_path, lambda q, g, fb: "drafted", Broken()).run("q", _context)

    assert result.verdict == "fallback"
    assert result.answer == "drafted"
    assert "fallback" in [e["phase"] for e in result.trace]


def test_writes_all_three_log_sinks(tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="ai_loop")
    result = _loop(tmp_path, lambda q, g, fb: "a", FakeReviewer(["approved"])).run("q", _context)

    # 1. stdout logger
    assert any("PLAN" in r.message for r in caplog.records)
    assert any("ADAPT" in r.message for r in caplog.records)
    # 2. JSONL
    lines = (tmp_path / "almanac.jsonl").read_text().splitlines()
    events = [json.loads(line) for line in lines]
    assert [e["phase"] for e in events] == ["plan", "act", "observe", "adapt"]
    assert all(e["run_id"] == result.run_id for e in events)
    # 3. markdown transcript
    transcript = (tmp_path / "reports" / "almanac" / f"{result.run_id}.md").read_text()
    assert "Plan → Act → Observe → Adapt" in transcript
    assert "## ACT" in transcript and "## OBSERVE" in transcript


def test_review_prompt_is_versioned_alongside_ai_dev():
    # The reviewer instruction is the runtime cousin of tools/ai-dev/prompts/observe.txt.
    assert "verdict" in ai_loop.PROMPT_REVIEW
    assert "approved" in ai_loop.PROMPT_REVIEW and "revise" in ai_loop.PROMPT_REVIEW

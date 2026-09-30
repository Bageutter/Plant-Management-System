"""The Perceive → Reason → Act → Observe → Repeat loop around a health assessment.

Loop mechanics run against the fake vision model and a scripted reviewer (no
Ollama); route tests check that every assessment carries its loop run.
"""

from __future__ import annotations

import json

import pytest

from agentic import WORKFLOW, HealthAssessmentLoop, observe_checks, perceive
from conftest import FakeOllama, FakeReviewer, make_assessment


def _loop(tmp_path, reviewer, client=None, max_iterations=2):
    return HealthAssessmentLoop(
        client or FakeOllama(), reviewer, str(tmp_path / "logs"), max_iterations=max_iterations
    )


def _phases(outcome):
    return [e["phase"] for e in outcome.trace]


# -- PERCEIVE and the deterministic OBSERVE checks ----------------------------------


def test_perceive_states_exactly_what_the_model_was_given():
    g = perceive("Yellow leaves", None, "Tomato", [{"id": 1}, {"id": 2}, {"id": 3}, {"id": 4}])
    assert g["evidence"] == "a written description only, and no photo"
    assert g["has_image"] is False and g["plant_ref"] == "Tomato"
    assert len(g["earlier_assessments"]) == 3  # capped

    assert perceive(None, "aGVsbG8=", None, None)["evidence"] == "one photo, and no written description"
    assert perceive("x", "aGVsbG8=", None, None)["evidence"] == "one photo and a written description"


def test_observe_checks_catch_inconsistent_or_ungrounded_drafts():
    text_only = perceive("Leaves yellow", None, None, None)
    good = FakeOllama()._result("Leaves yellow", None)
    assert observe_checks(good, text_only) == []

    bad = dict(good, status="healthy", health_score=20)
    assert any("outside the 60-100 band" in p for p in observe_checks(bad, text_only))

    sees_photo = dict(good, confidence_reason="In the photo the lower leaves are clearly yellow.")
    assert any("no photo was provided" in p for p in observe_checks(sees_photo, text_only))
    with_photo = perceive(None, "aGVsbG8=", None, None)
    assert observe_checks(sees_photo, with_photo) == []

    denies = dict(good, confidence_reason="Without a photo this is a guess.")
    assert any("denies the photo" in p for p in observe_checks(denies, with_photo))

    nothing_to_do = dict(good, recommendations=[])
    assert any("no recommendation" in p for p in observe_checks(nothing_to_do, text_only))

    healthy_but_severe = dict(good, status="healthy", health_score=90,
                              issues=[{"name": "Rot", "severity": "high", "evidence": ""}])
    assert any("high-severity" in p for p in observe_checks(healthy_but_severe, text_only))


# -- loop mechanics ------------------------------------------------------------------


def test_approved_first_pass_runs_each_phase_once(tmp_path):
    reviewer = FakeReviewer(["approved"])
    outcome = _loop(tmp_path, reviewer).run("Leaves yellow", None, "Tomato", history=[{"id": 9}])

    assert outcome.iterations == 1 and outcome.verdict == "approved" and outcome.reviewed
    assert _phases(outcome) == ["perceive", "reason", "act", "observe", "repeat"]
    assert outcome.trace[0]["evidence"] == "a written description only, and no photo"
    assert outcome.trace[0]["earlier_assessments"] == 1
    assert outcome.trace[3]["verdict"] == "approved" and outcome.trace[3]["reviewer"] == "fake-reviewer"
    assert outcome.trace[4]["decision"] == "accept"
    assert outcome.result["status"] == "at_risk"
    assert outcome.reviewer_model == "fake-reviewer"
    # The reviewer saw the grounding and the candidate as JSON.
    call = reviewer.calls[0]
    assert call["grounding"]["plant_ref"] == "Tomato"
    assert json.loads(call["draft"])["status"] == "at_risk"


def test_revise_carries_the_guidance_into_the_next_reason(tmp_path):
    client = FakeOllama()
    reviewer = FakeReviewer(["revise", "approved"])
    outcome = _loop(tmp_path, reviewer, client).run("Leaves yellow", None, "Tomato")

    assert outcome.iterations == 2 and outcome.verdict == "approved"
    assert _phases(outcome) == [
        "perceive", "reason", "act", "observe", "repeat", "reason", "act", "observe", "repeat"
    ]
    assert outcome.trace[4]["decision"] == "revise" and "fix iteration 1" in outcome.trace[4]["guidance"]
    assert client.calls[0]["feedback"] is None
    assert client.calls[1]["feedback"] == "fix iteration 1"
    assert outcome.trace[5]["carried_feedback"] == "fix iteration 1"


def test_iteration_cap_returns_the_last_candidate_marked_capped(tmp_path):
    outcome = _loop(tmp_path, FakeReviewer(["revise"]), max_iterations=2).run("Leaves yellow", None, None)
    assert outcome.iterations == 2 and outcome.verdict == "revised_capped"
    assert outcome.trace[-1]["decision"] == "stop_capped"
    assert outcome.result["status"] == "at_risk"  # still a usable assessment


def test_code_checks_force_a_revision_even_when_the_reviewer_approves(tmp_path):
    client = FakeOllama()
    client.script = [{"status": "healthy", "health_score": 20}, {}]  # inconsistent, then fine
    outcome = _loop(tmp_path, FakeReviewer(["approved"]), client).run("Leaves yellow", None, None)

    assert outcome.iterations == 2 and outcome.verdict == "approved"
    assert "outside the 60-100 band" in outcome.trace[3]["checks"]
    assert "outside the 60-100 band" in client.calls[1]["feedback"]


def test_without_a_reviewer_the_loop_runs_checks_only_and_reports_fallback(tmp_path):
    outcome = _loop(tmp_path, None).run("Leaves yellow", None, None)
    assert outcome.iterations == 1 and outcome.verdict == "fallback" and not outcome.reviewed
    assert outcome.trace[3]["reviewer"] == "(checks only)"
    assert outcome.reviewer_model is None


def test_reviewer_outage_degrades_to_checks_only(tmp_path):
    reviewer = FakeReviewer(["approved"])
    reviewer.fail = True
    outcome = _loop(tmp_path, reviewer).run("Leaves yellow", None, None)
    assert outcome.verdict == "fallback"
    assert [e["phase"] for e in outcome.trace] == ["perceive", "reason", "act", "fallback", "observe", "repeat"]
    assert "reviewer unavailable" in outcome.trace[3]["reason"]


def test_progress_sink_receives_phase_and_streamed_progress_events(tmp_path):
    seen = []
    outcome = _loop(tmp_path, FakeReviewer(["revise", "approved"])).run(
        "Leaves yellow", None, "Tomato", progress=seen.append
    )
    assert outcome.iterations == 2
    phases = [(e["phase"], e["iteration"]) for e in seen if e["type"] == "phase"]
    assert phases == [
        ("perceive", 0), ("reason", 1), ("observe", 1), ("repeat", 1), ("reason", 2), ("observe", 2)
    ]
    progress = [e for e in seen if e["type"] == "progress"]
    assert progress and progress[0]["phase"] == "reason" and progress[0]["iterations_max"] == 2
    assert progress[-1]["iteration"] == 2


def test_every_phase_is_written_to_stdout_jsonl_and_transcript(tmp_path, caplog):
    import logging

    caplog.set_level(logging.INFO, logger="ai_loop")
    outcome = _loop(tmp_path, FakeReviewer(["approved"])).run("Leaves yellow", None, "Tomato")

    assert any("PERCEIVE" in r.message for r in caplog.records)
    assert any("REPEAT" in r.message for r in caplog.records)

    lines = (tmp_path / "logs" / "health.jsonl").read_text(encoding="utf-8").splitlines()
    events = [json.loads(line) for line in lines]
    assert [e["phase"] for e in events] == ["perceive", "reason", "act", "observe", "repeat"]
    assert all(e["run_id"] == outcome.run_id and e["service"] == "health" for e in events)

    transcript = (tmp_path / "logs" / "reports" / "health" / f"{outcome.run_id}.md").read_text(encoding="utf-8")
    assert WORKFLOW in transcript and "## PERCEIVE" in transcript and "## REPEAT" in transcript
    assert outcome.transcript_path.endswith(f"{outcome.run_id}.md")


def test_model_failure_surfaces_as_an_error(tmp_path):
    from ai import AIUnavailableError

    client = FakeOllama()
    client.reachable = False
    with pytest.raises(AIUnavailableError):
        _loop(tmp_path, FakeReviewer(["approved"]), client).run("Leaves yellow", None, None)


# -- through the routes --------------------------------------------------------------


def test_every_assessment_records_its_loop_run(client, ai_loop_reviewer):
    ai_loop_reviewer.script = ["revise", "approved"]
    created = make_assessment(client, plant_ref="Tomato")

    assert created["loop"]["iterations"] == 2 and created["loop"]["verdict"] == "approved"
    assert created["loop"]["reviewed"] is True and created["loop"]["run_id"].startswith("health-")

    run = client.get(f"/plant-health-records/assessments/{created['id']}/loop")
    assert run.status_code == 200
    body = run.get_json()
    assert body["workflow"] == WORKFLOW and body["reviewer_model"] == "fake-reviewer"
    assert [e["phase"] for e in body["trace"]][:5] == ["perceive", "reason", "act", "observe", "repeat"]
    assert client.get("/plant-health-records/assessments/999/loop").status_code == 404

    page = client.get(f"/plant-health-records/{created['id']}/loop")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert "Perceive → Reason → Act → Observe → Repeat" in html
    assert 'data-loop-verdict="approved"' in html and 'data-phase="repeat"' in html
    assert "fake-reviewer" in html


def test_earlier_assessments_of_the_same_plant_are_perceived(client, fake_ai):
    first = make_assessment(client, plant_ref="Tomato")
    second = make_assessment(client, plant_ref="Tomato")
    make_assessment(client, plant_ref="Basil")

    assert fake_ai.calls[0]["history"] == []
    assert [h["id"] for h in fake_ai.calls[1]["history"]] == [first["id"]]
    assert fake_ai.calls[2]["history"] == []  # a different plant
    run = client.get(f"/plant-health-records/assessments/{second['id']}/loop").get_json()
    assert run["trace"][0]["earlier_assessments"] == 1


def test_assessment_card_and_record_page_show_the_loop_badge(client):
    fragment = client.post(
        "/plant-health-records/assessments",
        data={"plant_ref": "Chilli", "description": "Curling leaves"},
        headers={"HX-Request": "true"},
    )
    html = fragment.get_data(as_text=True)
    assert 'data-loop="approved"' in html and "1 iteration" in html
    record_id = int(html.split("Assessment #")[1].split()[0])
    page = client.get(f"/plant-health-records/{record_id}").get_data(as_text=True)
    assert f"/plant-health-records/{record_id}/loop" in page


def test_stream_emits_phase_events_before_the_result(client, ai_loop_reviewer):
    ai_loop_reviewer.script = ["revise", "approved"]
    response = client.post(
        "/plant-health-records/assessments/stream", data={"description": "Wilting", "plant_ref": "Mint"}
    )
    assert response.status_code == 200 and response.mimetype == "text/event-stream"
    events = [json.loads(p[6:]) for p in response.get_data(as_text=True).split("\n\n") if p.startswith("data: ")]
    kinds = [(e["type"], e.get("phase")) for e in events]
    assert kinds[0] == ("phase", "perceive")
    assert ("phase", "repeat") in kinds and kinds[-1] == ("done", None)
    assert events[-1]["loop"] == {"iterations": 2, "verdict": "approved", "reviewed": True}
    assert all(e["type"] != "error" for e in events)


def test_regenerate_records_a_new_loop_run(client):
    original = make_assessment(client)
    repeat = client.post(f"/plant-health-records/assessments/{original['id']}/regenerate").get_json()
    assert repeat["loop"]["run_id"] != original["loop"]["run_id"]
    assert client.get(f"/plant-health-records/assessments/{repeat['id']}/loop").status_code == 200


def test_deleting_an_assessment_removes_its_loop_run(app, client):
    from extensions import db
    from models import AssessmentLoopRun

    created = make_assessment(client)
    assert client.delete(f"/plant-health-records/assessments/{created['id']}").status_code == 204
    with app.app_context():
        assert db.session.query(AssessmentLoopRun).count() == 0

"""Live state is real, private to the chat owner, and shared across workers."""
import json

from ai_loop import AgenticLoop
from multi_agent import review_view
from progress import ProgressStore
from test_multi_agent_chat import chat as _chat_fixture, message_id

chat = _chat_fixture


def test_progress_is_readable_while_remote_run_is_still_executing(chat, tmp_path, monkeypatch):
    import app as app_module
    app, client, auth, calls, state = chat
    app.config['AI_PROGRESS_DIR'] = str(tmp_path / 'progress')
    key = 'a' * 32
    observed = []

    def remote(path, payload=None, workflow_id=None):
        if path == '/workflow/run':
            state.update(status='planning', history=[{'status': 'planning'}])
            # Read the public progress endpoint before the long request returns.
            observed.append(app.test_client().get(f'/ai/progress/{key}').get_json())
            state.update(status='awaiting_human_review')
        return dict(state)

    monkeypatch.setattr(app_module, 'request_workflow', remote)
    response = client.post('/ai/ask', data={'mode':'multi_agent', 'question':'Basil sunlight?', 'progress_id':key})
    assert response.status_code == 200
    assert observed[0]['phase'] == 'planning'
    assert observed[0]['phases'] == ['planning']
    assert 'owner' not in observed[0] and 'question' not in observed[0]
    assert client.get(f'/ai/progress/{key}').headers['Cache-Control'] == 'no-store'
    auth.user = {'id':202}
    assert client.get(f'/ai/progress/{key}').status_code == 404
    assert client.get('/ai/progress/not-an-id').status_code == 404


def test_progress_snapshots_work_across_instances_and_expire(tmp_path, monkeypatch):
    a = ProgressStore(tmp_path)
    b = ProgressStore(tmp_path)
    key = 'b' * 32
    a.start(key, 'user:1', 'planning')
    a.update(key, 'user:1', 'act')
    assert b.read(key, 'user:1')['phase'] == 'act'
    assert b.read(key, 'user:2') is None
    assert b.read('../private', 'user:1') is None
    saved = json.loads(a.path(key).read_text())
    monkeypatch.setattr('progress.time.time', lambda: saved['created'] + a.lifetime + 1)
    assert b.read(key, 'user:1') is None


def test_loop_callbacks_precede_actual_work_and_do_not_invent_review(tmp_path):
    events = []

    def context():
        assert events[-1] == 'plan'
        return {}, {}

    def draft(question, grounding, feedback):
        assert events[-1] == 'act'
        return 'Saved fact.'

    class Reviewer:
        def review(self, *args):
            assert events[-1] == 'observe'
            return {'verdict':'approved', 'issues':[], 'guidance':''}

    AgenticLoop('test', draft, Reviewer(), str(tmp_path), on_phase=events.append).run('Q', context)
    assert events == ['plan','act','observe','adapt']
    events.clear()
    AgenticLoop('test', draft, None, str(tmp_path), on_phase=events.append).run('Q', context)
    assert events == ['plan','act']  # A fallback must not claim OBSERVE or ADAPT.


def test_revision_resets_stage_completion_and_choices_require_intent(chat):
    view = review_view({'status':'planning', 'history':[{'status':x} for x in
                       ['planning','working','reviewing','changes_requested','planning']]})
    assert [s['state'] for s in view['stages']] == ['current','pending','pending','pending']
    app, client, auth, calls, state = chat
    client.post('/ai/ask', data={'mode':'multi_agent', 'question':'Basil sunlight?'})
    page = client.get(f'/ai/multi-agent/{message_id(app)}').text
    assert 'Approve answer' in page and 'Approve part' in page and 'Reject answer' in page
    assert '<select' not in page
    assert 'value="accept" x-model="decision" required checked' not in page
    assert client.post(f'/ai/multi-agent/{message_id(app)}', data={
        'action':'review', 'decision':'reject', 'feedback':''}).status_code == 400

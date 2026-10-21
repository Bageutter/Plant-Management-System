"""Shared workflows stay inside the authenticated Almanac conversation."""
import copy

import httpx
import pytest

import app as app_module
from app import create_app
from models import AIChatMessage


class Auth:
    user = {"id": 101}

    def current_user(self, _cookie):
        return self.user


@pytest.fixture
def chat(tmp_path, monkeypatch):
    app = create_app({"TESTING": True, "WTF_CSRF_ENABLED": False,
                      "MULTI_AGENT_ENABLED": True,
                      "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'chat.db'}",
                      "PLANT_IMAGE_FOLDER": str(tmp_path / 'images')})
    auth = Auth()
    app.extensions['auth_client'] = auth
    state = {"workflow_id": "owned-workflow", "status": "received", "task": "Basil sunlight?"}
    calls = []

    def remote(path, payload=None, workflow_id=None):
        calls.append((path, payload, workflow_id))
        if path.endswith('/run'):
            state.update(status='awaiting_human_review', plan={"steps": ["Read saved care"]},
                         result={"answer": "<script>Basil</script> needs full sun.",
                                 "insufficient_context": False, "cited_chunk_ids": ["basil:1"]},
                         evidence={"passages": [{"chunk_id": "basil:1", "text": "full sun"}]},
                         review={"recommendation": "accept", "issues": []})
        elif path.endswith('/review'):
            state.update(status={'accept': 'accepted', 'request_changes': 'changes_requested',
                                 'partially_accept': 'partially_accepted', 'reject': 'rejected'}[payload['decision']],
                         human_review=payload)
        return copy.deepcopy(state)

    monkeypatch.setattr(app_module, 'request_workflow', remote)
    return app, app.test_client(), auth, calls, state


def send(client):
    return client.post('/ai/ask', data={'mode': 'multi_agent', 'question': 'Basil sunlight?'})


def message_id(app):
    with app.app_context():
        return AIChatMessage.query.filter_by(role='assistant').one().id


def test_question_runs_agents_and_persists_evidence_in_chat(chat):
    app, client, auth, calls, state = chat
    response = send(client)
    assert response.status_code == 200
    assert [c[0] for c in calls] == ['/workflow', '/workflow/run']
    assert b'awaiting_human_review' in response.data and b'Save my review' in response.data
    assert b'&lt;script&gt;' in response.data and b'<script>Basil' not in response.data
    with app.app_context():
        assert AIChatMessage.query.count() == 2
        answer = AIChatMessage.query.filter_by(role='assistant').one()
        assert answer.owner_key == 'user:101'
        assert answer.evidence['result']['evidence']['passages'][0]['chunk_id'] == 'basil:1'
    page = client.get('/')
    assert b'Multi-Agent</button>' in page.data and b'Save my review' in page.data
    assert client.get('/integrations/multi-agent').status_code == 404
    assert b'Ask the Almanac agents' not in client.get('/integrations').data


def test_review_refresh_revision_and_multiple_owners(chat):
    app, client, auth, calls, state = chat
    send(client)
    url = f'/ai/multi-agent/{message_id(app)}'
    assert client.post(url, data={'action': 'review', 'decision': 'request_changes'}).status_code == 400
    response = client.post(url, data={'action': 'review', 'decision': 'request_changes',
                                     'feedback': 'Include the saved source title.', 'workflow_id': 'someone-else'})
    assert response.status_code == 200 and b'Run agents again' in response.data
    assert calls[-1][1]['workflow_id'] == 'owned-workflow'
    assert calls[-1][1]['reviewer_id'] == 'user:101'
    assert client.post(url, data={'action': 'run'}).status_code == 200
    assert client.post(url, data={'action': 'review', 'decision': 'accept'}).status_code == 200
    assert b'Your saved decision: accept' in client.get(url).data
    auth.user = {'id': 202}
    count = len(calls)
    assert client.get(url).status_code == 404
    assert client.post(url, data={'action': 'review', 'decision': 'reject'}).status_code == 404
    assert len(calls) == count
    auth.user = None
    assert send(client).status_code == 401
    assert client.get(url).status_code == 404


def test_outage_preserves_workflow_for_status_recovery(chat, monkeypatch):
    app, client, auth, calls, state = chat

    def remote(path, payload=None, workflow_id=None):
        if path == '/workflow':
            return copy.deepcopy(state)
        raise httpx.ReadTimeout('still running')

    monkeypatch.setattr(app_module, 'request_workflow', remote)
    response = send(client)
    assert response.status_code == 200 and b'Your question is saved' in response.data
    url = f'/ai/multi-agent/{message_id(app)}'
    assert b'Refresh agent status' in response.data
    assert client.get(url).status_code == 502
    monkeypatch.setattr(app_module, 'request_workflow', lambda *a, **kw: copy.deepcopy(state))
    assert client.get(url).status_code == 200
    assert client.post(url, data={'action': 'wrong'}).status_code == 400
    app.config['MULTI_AGENT_ENABLED'] = False
    assert client.get(url).status_code == 503
    assert send(client).status_code == 503


def test_create_failure_saves_nothing_and_csrf_protects_actions(chat, monkeypatch):
    app, client, auth, calls, state = chat

    def offline(*a, **kw):
        raise httpx.ConnectError('offline')

    monkeypatch.setattr(app_module, 'request_workflow', offline)
    assert send(client).status_code == 503
    with app.app_context():
        assert AIChatMessage.query.count() == 0
    app.config['WTF_CSRF_ENABLED'] = True
    assert send(client).status_code == 400
    assert client.post('/ai/multi-agent/1', data={'action': 'run'}).status_code == 400


@pytest.mark.parametrize('decision', ['partially_accept', 'reject'])
def test_other_human_decisions_and_clear(chat, decision):
    app, client, auth, calls, state = chat
    send(client)
    url = f'/ai/multi-agent/{message_id(app)}'
    response = client.post(url, data={'action': 'review', 'decision': decision, 'feedback': 'Test review.'})
    assert response.status_code == 200
    assert f'Your saved decision: {decision.replace("_", " ")}'.encode() in response.data
    assert client.post('/ai/clear').status_code == 200
    assert client.get(url).status_code == 404



def test_human_review_is_readable_and_defaults_to_changes(chat):
    app, client, auth, calls, state = chat
    send(client)
    state['review'] = {'recommendation': 'revise', 'issues': ['Remove unused citation: basil:1']}
    state['evidence'] = {'passages': [
        {'chunk_id': 'basil:1', 'title': 'Basil - Genovese — plant reference',
         'url': 'javascript:alert(1)', 'text': 'Sun needs: full sun.\nWater needs: moderate.'}]}
    response = client.get(f'/ai/multi-agent/{message_id(app)}')
    visible = response.text.split('<summary>Technical details</summary>')[0]
    assert 'Changes recommended' in visible
    assert 'Source attribution needs checking for Basil - Genovese' in visible
    assert 'does not prove the source is unused' in visible
    assert 'basil:1' not in visible and '"issues"' not in visible
    assert 'javascript:' not in visible
    assert 'Not recorded' in visible and 'full sun' in visible
    assert 'value="request_changes" selected' in visible
    assert 'Use the review concerns as feedback' in visible
    assert 'Technical details' in response.text

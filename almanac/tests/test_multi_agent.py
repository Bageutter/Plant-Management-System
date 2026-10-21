"""Validate the real HTTP adapter without a model dependency."""
import httpx
import pytest
from flask import Flask
import multi_agent


@pytest.mark.parametrize('body', [[], {}, {'workflow_id': 7}, {'workflow_id': 'abc'},
                                   {'workflow_id': '', 'status': 'received'},
                                   {'workflow_id': 'abc', 'status': 'reviewing', 'result': None}, 'invalid-json'])
def test_rejects_invalid_server_responses(monkeypatch, body):
    app = Flask(__name__)
    app.config['MULTI_AGENT_SERVER_URL'] = 'http://local:8003'
    transport = httpx.MockTransport(lambda req: httpx.Response(
        200, content=b'not json') if body == 'invalid-json' else httpx.Response(200, json=body))
    real_client = httpx.Client
    monkeypatch.setattr(multi_agent.httpx, 'Client', lambda **kw: real_client(transport=transport, **kw))
    with app.app_context(), pytest.raises(RuntimeError):
        multi_agent.request_workflow('/workflow', {'task': 'Tomato?'})


def test_adapter_status_query_and_post_payload(monkeypatch):
    app = Flask(__name__)
    app.config['MULTI_AGENT_SERVER_URL'] = 'http://local:8003/'
    calls = []

    def handle(req):
        calls.append(req)
        return httpx.Response(200, json={'workflow_id': 'abc', 'status': 'received'})

    real_client = httpx.Client
    monkeypatch.setattr(multi_agent.httpx, 'Client', lambda **kw: real_client(transport=httpx.MockTransport(handle), **kw))
    with app.app_context():
        multi_agent.request_workflow('/workflow', {'task': 'Tomato?'})
        multi_agent.request_workflow('/workflow/status', workflow_id='abc')
    assert calls[0].method == 'POST' and b'Tomato?' in calls[0].content
    assert calls[1].method == 'GET' and calls[1].url.params['id'] == 'abc'

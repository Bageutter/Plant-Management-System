import asyncio
import httpx
from mcp import Client
from server import create_server
from settings import Settings


def test_rag_contract_and_refresh_gate():
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={'passages': [], 'mode': 'chroma'})
    async def check():
        async with Client(create_server(Settings(), transport=httpx.MockTransport(handler))) as client:
            result = await client.call_tool('retrieve_context', {'question': 'Tomatoes?'})
            assert not result.is_error
            assert calls[-1].url.path == '/rag/retrieve'
            for name, args in [('refresh_corpus', {'source': 'almanac'}),
                               ('retrieve_context', {'question': 'x', 'top_k': 99}),
                               ('answer_question', {'question': 'x', 'source': 'vgarden'})]:
                result = await client.call_tool(name, args)
                assert result.is_error
            assert len(calls) == 1
    asyncio.run(check())


def test_rag_dependency_failure():
    def handler(request):
        raise httpx.ConnectError('offline', request=request)
    async def check():
        async with Client(create_server(Settings(), transport=httpx.MockTransport(handler))) as client:
            assert (await client.call_tool('answer_question', {'question': 'Tomatoes?'})).is_error
    asyncio.run(check())


def test_answer_question_returns_insufficient_context_without_error():
    def handler(request):
        return httpx.Response(200, json={
            'answer': None,
            'confidence': 'insufficient',
            'insufficient_context': True,
            'citations': [],
        })

    async def check():
        async with Client(create_server(Settings(), transport=httpx.MockTransport(handler))) as client:
            result = await client.call_tool('answer_question', {'question': 'Tomatoes?'})
            assert not result.is_error

    asyncio.run(check())

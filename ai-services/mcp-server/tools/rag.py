"""Bounded local RAG operations. Private garden access is deliberately not exposed
through this shared, unauthenticated MCP endpoint; the app owns that permission.
"""
from typing import Annotated, Literal
from pydantic import Field, BaseModel, ConfigDict
from mcp.types import ToolAnnotations
from mcp.server.mcpserver.exceptions import ToolError
from tools.common import FeatureClient, READ_ONLY, guard

Question = Annotated[str, Field(min_length=1, max_length=500)]
TopK = Annotated[int, Field(strict=True, ge=1, le=10)]
Source = Literal['almanac', 'health']


class RetrievalResult(BaseModel):
    mode: str
    passages: list[dict]

class AnswerResult(BaseModel):
    model_config = ConfigDict(extra='allow')
    answer: str | None
    confidence: str
    insufficient_context: bool
    citations: list[dict]

class RefreshResult(BaseModel):
    model_config = ConfigDict(extra='allow')
    source: str
    chunks: int
    documents: int
    embedded: bool

def register(server, settings, *, transport=None):
    api = FeatureClient('RAG', settings.rag_url, settings.assess_timeout, transport=transport)

    @server.tool(annotations=READ_ONLY)
    def retrieve_context(question: Question, source: Source = 'almanac', top_k: TopK = 5) -> RetrievalResult:
        """Find up to ten saved passages, returning source IDs, text and ranking scores.
        Scores measure retrieval relevance, not the probability that facts are true.
        Unavailable dependencies raise a tool error; no answer is invented.
        """
        guard(settings)
        return RetrievalResult.model_validate(api.post('rag/retrieve', {'question': question, 'sources': [source], 'top_k': top_k}))

    @server.tool(annotations=READ_ONLY)
    def answer_question(question: Question, source: Source = 'almanac', top_k: TopK = 5) -> AnswerResult:
        """Answer from saved passages with citations and an evidence category.
        Insufficient context is a normal result, not permission to guess.
        """
        guard(settings)
        return AnswerResult.model_validate(api.post('rag/query', {'question': question, 'sources': [source], 'top_k': top_k}))

    @server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                           idempotentHint=True, openWorldHint=False))
    def refresh_corpus(source: Source) -> RefreshResult:
        """Rebuild one derived search index from its fixed application source.
        Requires operator configuration MCP_RAG_REFRESH_ENABLED=true.
        Never changes original plant or health records.
        """
        guard(settings)
        if not settings.rag_refresh_enabled:
            raise ToolError('Corpus refresh is disabled; an operator must enable it.')
        return RefreshResult.model_validate(api.post(f'rag/ingest/{source}', {}))

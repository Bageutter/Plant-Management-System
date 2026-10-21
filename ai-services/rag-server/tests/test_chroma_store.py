import pytest

pytest.importorskip("chromadb", reason="optional backend: pip install -r requirements-chroma.txt")
from chroma_store import ChromaStore  # noqa: E402
from store import Chunk


def chunk(source_id, vector, part='record'):
    return Chunk('vgarden', source_id, part, 'Garden', 'Tomatoes planted here', embedding=vector)


def test_persistence_scope_and_refresh(tmp_path):
    store = ChromaStore(str(tmp_path), 'test-model')
    store.replace_source('vgarden', [chunk('1', [1., 0.]), chunk('2', [.9, .1])], 2)
    reopened = ChromaStore(str(tmp_path), 'test-model')
    assert reopened.count() == 2
    assert [c.source_id for c in reopened.vector_chunks([1., 0.], ['vgarden'], source_id='2')] == ['2']
    assert reopened.vector_chunks([1., 0.], ['vgarden'], source_id='99') == []
    with pytest.raises(ValueError):
        reopened.replace_source('vgarden', [chunk('2', [])], 1)
    assert reopened.count() == 2
    reopened.replace_source('vgarden', [chunk('2', [0., 1.])], 1)
    assert reopened.get('vgarden:1:record') is None
    reopened.replace_source('vgarden', [], 0)
    assert reopened.count() == 0


def test_model_change_requires_new_index(tmp_path):
    store = ChromaStore(str(tmp_path), 'model-one')
    store.replace_source('vgarden', [chunk('1', [1., 0.])], 1)
    with pytest.raises(ValueError, match='model changed'):
        ChromaStore(str(tmp_path), 'model-two')


def test_deterministic_vectors_persist_and_query_through_http(tmp_path, monkeypatch):
    from app import create_app
    from embeddings import DETERMINISTIC_MODEL, build_embedder
    def forbidden(*args, **kwargs):
        pytest.fail('retrieval must work without Ollama')
    monkeypatch.setattr('embeddings.requests.post', forbidden)
    monkeypatch.setattr('embeddings.requests.get', forbidden)
    config = {'TESTING': True, 'RAG_ENABLED': True, 'RAG_BACKEND': 'chroma',
        'RAG_CHROMA_PATH': str(tmp_path), 'RAG_EMBED_MODEL': DETERMINISTIC_MODEL}
    app = create_app(config)
    store = app.extensions['chunk_store']
    embedder = build_embedder(app.config)
    texts = ['Tomato aphids infestation', 'Basil watering schedule']
    vectors = embedder.embed(texts)
    passages = [Chunk('almanac', str(i), 'record', text, text, embedding=vector)
        for i, (text, vector) in enumerate(zip(texts, vectors))]
    store.replace_source('almanac', passages, 2)
    reopened = ChromaStore(str(tmp_path), DETERMINISTIC_MODEL)
    assert all(len(c.embedding) == 256 for c in reopened.chunks())
    assert reopened.vector_chunks(embedder.embed(['Tomato aphids'])[0], ['almanac'])[0].source_id == '0'
    result = app.test_client().post('/rag/retrieve', json={'question': 'Tomato aphids', 'sources': ['almanac'], 'top_k': 1})
    assert result.status_code == 200
    assert result.json['mode'] == 'chroma'
    assert result.json['passages'][0]['chunk_id'] == 'almanac:0:record'
    with pytest.raises(ValueError, match='256 dimensions'):
        store.replace_source('almanac', [Chunk('almanac', '3', 'record', 'Bad', 'Bad', embedding=[1., 0.])], 1)
    assert store.count() == 2
    with pytest.raises(ValueError, match='model changed'):
        ChromaStore(str(tmp_path), 'bge-m3:latest')


def test_health_ingestion_uses_same_vectors_as_queries(tmp_path, monkeypatch):
    from embeddings import DETERMINISTIC_MODEL, build_embedder
    from sources import health
    config = {'RAG_EMBED_MODEL': DETERMINISTIC_MODEL, 'HEALTH_SERVICE_URL': 'http://health'}
    monkeypatch.setattr(health, 'fetch_assessments', lambda config: [
        {'id': 1, 'plant_name': 'Tomato', 'summary': 'Aphids on tomato leaves'}])
    store = ChromaStore(str(tmp_path), DETERMINISTIC_MODEL)
    result = health.ingest(config, store)
    assert result['embedded'] is True
    assert result['documents'] == 1
    embedder = build_embedder(config)
    for passage in store.chunks():
        assert passage.embedding == embedder.embed([f'{passage.title}\n{passage.text}'])[0]
        assert len(passage.embedding) == 256
    assert store.vector_chunks(embedder.embed(['Tomato aphids'])[0], ['health'])[0].source_id == '1'

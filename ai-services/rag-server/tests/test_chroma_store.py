import pytest
from chroma_store import ChromaStore
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

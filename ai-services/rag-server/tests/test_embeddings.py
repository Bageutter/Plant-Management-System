"""Repeatability and compatibility contracts for the lecture's local vectors."""
import json
import math
import os
import subprocess
import sys

import pytest

from embeddings import DETERMINISTIC_MODEL, DeterministicEmbedder, OllamaEmbedder, build_embedder


def test_vectors_are_finite_normalized_256d_and_need_no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('deterministic embeddings must not call Ollama')
    monkeypatch.setattr('embeddings.requests.post', forbidden)
    monkeypatch.setattr('embeddings.requests.get', forbidden)
    embedder = build_embedder({'RAG_EMBED_MODEL': DETERMINISTIC_MODEL})
    texts = ['Tomato aphids', 'Basil needs water', '', '!!!', '番茄 café']
    vectors = embedder.embed(texts)
    assert embedder.embed([]) == []
    assert vectors == embedder.embed(texts)
    for vector in vectors:
        assert len(vector) == 256
        assert all(math.isfinite(value) for value in vector)
        assert sum(value * value for value in vector) == pytest.approx(1)
    assert vectors[0] != vectors[1]
    assert embedder.embed(['ＣＡＦÉ tomato!']) == embedder.embed(['café TOMATO'])


def test_repeatability_across_python_hash_seeds():
    script = 'import json; from embeddings import DeterministicEmbedder; print(json.dumps(DeterministicEmbedder().embed(["Tomato aphids"])))'
    outputs = [subprocess.check_output([sys.executable, '-c', script],  # noqa: S603 -- fixed Python interpreter and literal test script
        env={**os.environ, 'PYTHONHASHSEED': seed}, text=True) for seed in ['1', '99']]
    assert json.loads(outputs[0]) == json.loads(outputs[1]) == DeterministicEmbedder().embed(['Tomato aphids'])


def test_factory_preserves_explicit_ollama_and_lexical_options():
    assert isinstance(build_embedder({}), DeterministicEmbedder)
    assert build_embedder({'RAG_EMBED_MODEL': ''}) is None
    assert isinstance(build_embedder({'RAG_EMBED_MODEL': 'bge-m3:latest', 'OLLAMA_URL': 'http://localhost:11434'}), OllamaEmbedder)

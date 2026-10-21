"""Deterministic local embeddings, with optional Ollama (``/api/embed``).

The default versioned 256D function needs no model runtime. Explicit Ollama
models remain optional. SQLite can fall back to lexical retrieval if embeddings
are unavailable; Chroma requires embeddings and fails a refresh without replacing
the active index. Nothing leaves the local network.
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
import unicodedata

import requests

logger = logging.getLogger(__name__)


class EmbeddingUnavailable(RuntimeError):
    pass


DETERMINISTIC_MODEL = "deterministic-256-v1"
DETERMINISTIC_DIMENSIONS = 256


class DeterministicEmbedder:
    """Local feature hashing, shared by passage ingestion and query retrieval.

    NFKC/casefolded word counts map through SHA-256 into 256 positive buckets,
    then L2 normalization makes cosine similarity independent of text length.
    The versioned model ID must change if this algorithm changes. This is lexical
    overlap with hash collisions, not a learned semantic embedding model.
    """

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            tokens = re.findall(r"\w+", unicodedata.normalize("NFKC", text).casefold())
            vector = [0.0] * DETERMINISTIC_DIMENSIONS
            # Keep blank/punctuation-only passages valid for Chroma cosine search.
            for token in tokens or [""]:
                bucket = hashlib.sha256(token.encode("utf-8")).digest()[0]
                vector[bucket] += 1.0
            norm = math.sqrt(sum(value * value for value in vector))
            vectors.append([value / norm for value in vector])
        return vectors


class OllamaEmbedder:
    def __init__(
        self,
        base_url: str,
        model: str,
        timeout: int = 120,
        auto_pull: bool = True,
        pull_timeout: int = 1800,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.auto_pull = auto_pull
        self.pull_timeout = pull_timeout
        self._ready = False

    def ensure_model(self) -> None:
        if self._ready:
            return
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=5)
            response.raise_for_status()
            names = {m.get("name", "") for m in response.json().get("models", [])}
        except (requests.RequestException, ValueError) as exc:
            raise EmbeddingUnavailable(f"Cannot reach Ollama at {self.base_url}") from exc
        if self.model in names or f"{self.model}:latest" in names:
            self._ready = True
            return
        if not self.auto_pull:
            raise EmbeddingUnavailable(f"Embedding model '{self.model}' is not installed")
        logger.info("pulling embedding model %s", self.model)
        try:
            response = requests.post(
                f"{self.base_url}/api/pull",
                json={"model": self.model, "stream": False},
                timeout=self.pull_timeout,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise EmbeddingUnavailable(f"Could not pull embedding model '{self.model}'") from exc
        self._ready = True

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        self.ensure_model()
        try:
            response = requests.post(
                f"{self.base_url}/api/embed",
                json={"model": self.model, "input": texts},
                timeout=self.timeout,
            )
            response.raise_for_status()
            vectors = response.json().get("embeddings")
        except (requests.RequestException, ValueError) as exc:
            raise EmbeddingUnavailable(f"Embedding call failed: {exc.__class__.__name__}") from exc
        if not isinstance(vectors, list) or len(vectors) != len(texts):
            raise EmbeddingUnavailable("Ollama returned an unexpected embeddings shape")
        return [[float(x) for x in vector] for vector in vectors]


def build_embedder(config) -> DeterministicEmbedder | OllamaEmbedder | None:
    """An embedder from app config, or None when ``RAG_EMBED_MODEL`` is empty."""

    model = config.get("RAG_EMBED_MODEL", DETERMINISTIC_MODEL)
    if not model:
        return None
    if model == DETERMINISTIC_MODEL:
        return DeterministicEmbedder()
    return OllamaEmbedder(
        base_url=config["OLLAMA_URL"],
        model=model,
        timeout=config.get("OLLAMA_TIMEOUT", 120),
        auto_pull=config.get("OLLAMA_AUTO_PULL", True),
        pull_timeout=config.get("OLLAMA_PULL_TIMEOUT", 1800),
    )

"""Optional dense embeddings from local Ollama (``/api/embed``).

Embeddings are a best-effort enhancement: when the embedding model is not
configured, not installed, or Ollama is down, retrieval silently stays lexical and
the response says so (``retrieval.mode``). Nothing leaves the local network.
"""

from __future__ import annotations

import logging

import requests

logger = logging.getLogger(__name__)


class EmbeddingUnavailable(RuntimeError):
    pass


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


def build_embedder(config) -> OllamaEmbedder | None:
    """An embedder from app config, or None when ``RAG_EMBED_MODEL`` is empty."""

    model = config.get("RAG_EMBED_MODEL")
    if not model:
        return None
    return OllamaEmbedder(
        base_url=config["OLLAMA_URL"],
        model=model,
        timeout=config.get("OLLAMA_TIMEOUT", 120),
        auto_pull=config.get("OLLAMA_AUTO_PULL", True),
        pull_timeout=config.get("OLLAMA_PULL_TIMEOUT", 1800),
    )

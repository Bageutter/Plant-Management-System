"""Environment-driven configuration for the shared RAG server.

The server is a plain local process (Release 1 forbids containerising it), so
everything comes from environment variables with localhost defaults. Feature
services are reached through the nginx proxy on :3000; the model is local Ollama.
"""

from __future__ import annotations

import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

KNOWN_SOURCES = ("health", "almanac", "vgarden")
CONFIDENCE_CATEGORIES = ("high", "medium", "low", "insufficient")


def _as_bool(value: str | None, default: bool) -> bool:
    if value is None or not value.strip():
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class Config:
    RAG_BACKEND = os.getenv("RAG_BACKEND", "sqlite")
    RAG_CHROMA_PATH = os.getenv("RAG_CHROMA_PATH", os.path.join(BASE_DIR, "instance", "chroma"))
    # Operational switch. CI sets RAG_ENABLED=false: the server still starts and
    # answers /healthz, but every retrieval/ingest endpoint returns 503.
    RAG_ENABLED = _as_bool(os.environ.get("RAG_ENABLED"), True)
    RAG_HOST = os.environ.get("RAG_HOST", "127.0.0.1")
    RAG_PORT = int(os.environ.get("RAG_PORT", "5106"))

    # SQLite chunk store. Kept under instance/ (git-ignored).
    RAG_DATABASE_PATH = os.environ.get(
        "RAG_DATABASE_PATH", os.path.join(BASE_DIR, "instance", "rag.db")
    )

    # Feature services, via the proxy. Health and Almanac sources are implemented.
    HEALTH_SERVICE_URL = os.environ.get("HEALTH_SERVICE_URL", "http://127.0.0.1:3000/health")
    # Browser-facing origin used in citation links (the proxy, as the user sees it).
    HEALTH_PUBLIC_URL = os.environ.get("HEALTH_PUBLIC_URL", "http://localhost:3000/health")
    ALMANAC_SERVICE_URL = os.environ.get("ALMANAC_SERVICE_URL", "http://127.0.0.1:3000/almanac")
    ALMANAC_PUBLIC_URL = os.environ.get("ALMANAC_PUBLIC_URL", "http://localhost:3000/almanac")
    VGARDEN_SERVICE_URL = os.environ.get("VGARDEN_SERVICE_URL", "http://127.0.0.1:3000/vgarden")
    VGARDEN_PUBLIC_URL = os.environ.get("VGARDEN_PUBLIC_URL", "http://localhost:3000/vgarden")
    # Garden state is private per-owner (unlike the public Almanac catalogue or Plant
    # Health assessments), so bulk ingestion authenticates with the same shared
    # secret vgarden already uses for auth's server-to-server calls
    # (INTER_SERVICE_SECRET in docker-compose.yml / vgarden's own config).
    VGARDEN_SERVICE_TOKEN = os.environ.get(
        "VGARDEN_SERVICE_TOKEN", "dev-inter-service-secret-change-me"
    )
    SERVICE_TIMEOUT = float(os.environ.get("SERVICE_TIMEOUT", "15"))

    # Local Ollama only. Answering model matches the project's chat features;
    # the embedding model is optional (empty -> lexical retrieval only).
    OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434").rstrip("/")
    OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:4b-instruct")
    OLLAMA_TIMEOUT = int(os.environ.get("OLLAMA_TIMEOUT", "120"))
    OLLAMA_AUTO_PULL = _as_bool(os.environ.get("OLLAMA_AUTO_PULL"), True)
    OLLAMA_PULL_TIMEOUT = int(os.environ.get("OLLAMA_PULL_TIMEOUT", "1800"))
    RAG_EMBED_MODEL = os.environ.get("RAG_EMBED_MODEL", "nomic-embed-text")

    # Retrieval budgets and the relevance gate that triggers "insufficient context".
    RAG_TOP_K = int(os.environ.get("RAG_TOP_K", "5"))
    RAG_MAX_TOP_K = 10
    RAG_MIN_COVERAGE = float(os.environ.get("RAG_MIN_COVERAGE", "0.34"))
    RAG_MIN_SIMILARITY = float(os.environ.get("RAG_MIN_SIMILARITY", "0.45"))
    RAG_MAX_QUESTION_CHARS = 500
    RAG_MAX_ANSWER_CHARS = 2000

"""HTTP surface of the shared RAG server.

Feature backends call the JSON endpoints; the small HTMX page at ``/`` exists so
the server can be validated on its own from a browser or a terminal.
"""

from __future__ import annotations

import requests
from flask import Blueprint, current_app, jsonify, render_template, request

import pipeline
from config import KNOWN_SOURCES
from sources import SourceNotImplemented, SourceUnavailable, almanac, health, vgarden

bp = Blueprint("rag", __name__)

SOURCE_MODULES = {"health": health, "almanac": almanac, "vgarden": vgarden}


def _store():
    return current_app.extensions["chunk_store"]


def _wants_html() -> bool:
    if request.headers.get("HX-Request") == "true":
        return True
    accept = request.accept_mimetypes
    return bool(accept.provided) and accept["text/html"] > accept["application/json"]


def _error(message: str, code: int, *, extra: dict | None = None):
    if _wants_html():
        return render_template("_error.html", message=message, code=code), code
    body = {"error": message, "status_code": code}
    if extra:
        body.update(extra)
    return jsonify(body), code


def _ollama_reachable() -> bool:
    try:
        response = requests.get(f"{current_app.config['OLLAMA_URL']}/api/tags", timeout=3)
        response.raise_for_status()
        return True
    except requests.RequestException:
        return False


# -- infrastructure ---------------------------------------------------------


@bp.route("/healthz")
def healthz():
    ai_up = _ollama_reachable()
    body = {
        "service": "rag-server",
        "status": "ok" if ai_up else "degraded",
        "enabled": current_app.config["RAG_ENABLED"],
        "chunks": _store().count(),
        "sources": sorted(KNOWN_SOURCES),
        "ai": {
            "url": current_app.config["OLLAMA_URL"],
            "model": current_app.config["OLLAMA_MODEL"],
            "embed_model": current_app.config["RAG_EMBED_MODEL"] or None,
            "reachable": ai_up,
        },
    }
    return jsonify(body), 200 if ai_up else 503


@bp.before_request
def _enforce_enabled():
    """Everything except liveness and the landing page is switched off by RAG_ENABLED."""

    if current_app.config["RAG_ENABLED"] or request.endpoint in ("rag.healthz", "rag.index"):
        return None
    return _error(
        "The shared RAG server is disabled by its configuration (RAG_ENABLED=false). "
        "No context was retrieved and no answer was generated.",
        503,
        extra={"enabled": False},
    )


# -- UI -----------------------------------------------------------------------


@bp.route("/")
def index():
    return render_template(
        "index.html",
        sources=_store().sources(),
        known_sources=KNOWN_SOURCES,
        enabled=current_app.config["RAG_ENABLED"],
    )


# -- knowledge sources -------------------------------------------------------


@bp.route("/rag/sources")
def sources():
    indexed = {row["source"]: row for row in _store().sources()}
    return jsonify(
        [
            {
                "source": name,
                "implemented": bool(getattr(SOURCE_MODULES[name], "IMPLEMENTED", False)),
                "documents": indexed.get(name, {}).get("documents", 0),
                "chunks": indexed.get(name, {}).get("chunks", 0),
                "last_indexed_at": indexed.get(name, {}).get("last_indexed_at"),
            }
            for name in KNOWN_SOURCES
        ]
    )


@bp.route("/rag/ingest/<source>", methods=["POST"])
def ingest(source: str):
    module = SOURCE_MODULES.get(source)
    if module is None:
        return _error(
            f"Unknown source '{source}'. Known sources: {', '.join(KNOWN_SOURCES)}.", 404
        )
    try:
        result = module.ingest(current_app.config, _store())
    except SourceNotImplemented as exc:
        return _error(str(exc), 501, extra={"source": source, "tracking": exc.tracking})
    except SourceUnavailable as exc:
        return _error(str(exc), 502, extra={"source": source})
    return jsonify(result)


# -- grounded answers ----------------------------------------------------------


@bp.route("/rag/query", methods=["POST"])
def query():
    try:
        question, chosen, top_k = _read_query()
    except ValueError as exc:
        return _error(str(exc), 400)

    try:
        result = pipeline.answer(
            question,
            sources=chosen,
            top_k=top_k,
            config=current_app.config,
            store=_store(),
        )
    except pipeline.ModelUnavailable as exc:
        return _error(str(exc), 503)

    if _wants_html():
        return render_template("_answer.html", result=result)
    return jsonify(result)


def _read_query() -> tuple[str, tuple[str, ...], int]:
    data = request.get_json(silent=True) if request.is_json else request.form
    data = data or {}
    max_chars = current_app.config["RAG_MAX_QUESTION_CHARS"]

    question = data.get("question")
    if not isinstance(question, str) or not question.strip():
        raise ValueError("Provide a non-empty 'question'.")
    question = question.strip()
    if len(question) > max_chars:
        raise ValueError(f"'question' must be {max_chars} characters or fewer.")

    raw_sources = data.get("sources")
    if raw_sources is None or raw_sources == "":
        chosen: tuple[str, ...] = KNOWN_SOURCES
    else:
        if isinstance(raw_sources, str):
            raw_sources = [s.strip() for s in raw_sources.split(",") if s.strip()]
        if not isinstance(raw_sources, list) or not raw_sources:
            raise ValueError("'sources' must be a non-empty list of source names.")
        unknown = [s for s in raw_sources if s not in KNOWN_SOURCES]
        if unknown:
            raise ValueError(
                f"Unknown sources: {', '.join(map(str, unknown))}. "
                f"Known sources: {', '.join(KNOWN_SOURCES)}."
            )
        chosen = tuple(dict.fromkeys(raw_sources))

    top_k = data.get("top_k", current_app.config["RAG_TOP_K"])
    try:
        top_k = int(top_k)
    except (TypeError, ValueError) as exc:
        raise ValueError("'top_k' must be an integer.") from exc
    if not 1 <= top_k <= current_app.config["RAG_MAX_TOP_K"]:
        raise ValueError(f"'top_k' must be between 1 and {current_app.config['RAG_MAX_TOP_K']}.")

    return question, chosen, top_k

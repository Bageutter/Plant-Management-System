"""Almanac UI access to the group's local MCP and RAG servers."""

import asyncio
import re

import httpx
from flask import Blueprint, current_app, jsonify, render_template, request
from mcp import Client

from extensions import csrf

integrations = Blueprint("integrations", __name__, url_prefix="/integrations")


def _respond(body, mode, status=200):
    if request.is_json:
        return jsonify(body), status
    return render_template("_integration_result.html", result=body, mode=mode), status


def _enabled(mode):
    return current_app.config[f"{mode.upper()}_ENABLED"]


def _data():
    data = request.get_json(silent=True) if request.is_json else request.form
    if data is None or not hasattr(data, "get"):
        raise ValueError("Send a form or a JSON object.")
    return data


def _text(data, key, maximum, default=""):
    value = data.get(key, default)
    if not isinstance(value, str) or len(value.strip()) > maximum:
        raise ValueError(f"{key} must be text, at most {maximum} characters.")
    return value.strip()


async def _call_tool(target, tool, arguments):
    async with Client(target, read_timeout_seconds=30) as client:
        result = await client.call_tool(tool, arguments)
    return {
        "tool": tool,
        "is_error": bool(result.is_error),
        "structured_content": None if result.is_error else result.structured_content,
        "text": " ".join(getattr(block, "text", "") for block in result.content or []),
    }


@integrations.get("")
def index():
    return render_template("integrations.html", mcp_enabled=_enabled("mcp"), rag_enabled=_enabled("rag"))


@integrations.post("/mcp")
@csrf.exempt  # Public, read-only catalogue lookups; no writes or private records.
def mcp():
    if not _enabled("mcp"):
        return _respond({"error": "Catalogue tools are disabled (MCP_ENABLED=false)."}, "mcp", 503)
    try:
        data = _data()
        tool = data.get("tool", "search_almanac_catalogue")
        if tool == "search_almanac_catalogue":
            kind = data.get("kind", "all")
            if kind not in ("all", "plant", "pest", "disease"):
                raise ValueError("Choose plants, pests, diseases, or all references.")
            raw_limit = data.get("limit", 20)
            if isinstance(raw_limit, bool) or not str(raw_limit).isdigit():
                raise ValueError("limit must be a whole number from 1 to 50.")
            limit = int(raw_limit)
            if not 1 <= limit <= 50:
                raise ValueError("limit must be a whole number from 1 to 50.")
            arguments = {"query": _text(data, "query", 120), "kind": kind, "limit": limit}
        elif tool == "get_almanac_plant":
            slug = _text(data, "slug", 100)
            if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
                raise ValueError("Use a plant slug returned by the catalogue search.")
            arguments = {"slug": slug}
        else:
            raise ValueError("Only the two read-only Almanac tools are available here.")
    except ValueError as exc:
        return _respond({"error": str(exc)}, "mcp", 400)
    try:
        result = asyncio.run(_call_tool(current_app.config["MCP_SERVER_URL"], tool, arguments))
    except Exception:  # The MCP SDK also wraps transport errors in exception groups.
        current_app.logger.warning("Almanac MCP request failed", exc_info=True)
        return _respond({"error": "The shared catalogue tools are unavailable. Try again later."}, "mcp", 502)
    return _respond(result, "mcp", 502 if result["is_error"] else 200)


def _rag_request(path, payload=None):
    response = httpx.post(
        current_app.config["RAG_SERVER_URL"].rstrip("/") + path,
        json=payload,
        timeout=180,
        follow_redirects=False,
    )
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict):
        raise ValueError("Expected a RAG response object.")
    return body


@integrations.post("/rag")
@csrf.exempt  # Public reference questions; no account history is sent or stored.
def rag():
    if not _enabled("rag"):
        return _respond({"error": "Answers with sources are disabled (RAG_ENABLED=false)."}, "rag", 503)
    try:
        question = _text(_data(), "question", 500)
        if not question:
            raise ValueError("Enter a question first.")
    except ValueError as exc:
        return _respond({"error": str(exc)}, "rag", 400)
    try:
        result = _rag_request("/rag/query", {"question": question, "sources": ["almanac"]})
    except (httpx.HTTPError, ValueError):
        return _respond({"error": "Answers with sources are unavailable. Check the local RAG server and model."}, "rag", 502)
    return _respond(result, "rag")


@integrations.post("/rag/sync")
def sync():
    # Replacing the shared index costs work; require the existing login and CSRF token.
    user = current_app.extensions["auth_client"].current_user(request.headers.get("Cookie", ""))
    if not user:
        return _respond({"error": "Log in to refresh the reference index."}, "sync", 401)
    if not _enabled("rag"):
        return _respond({"error": "Reference indexing is disabled (RAG_ENABLED=false)."}, "sync", 503)
    try:
        result = _rag_request("/rag/ingest/almanac")
    except (httpx.HTTPError, ValueError):
        return _respond({"error": "The index could not be refreshed. Check that both local services are running."}, "sync", 502)
    return _respond(result, "sync")


def chat_reference_result(question, mode):
    """Use the same bounded, read-only services as the reference tools page."""
    if not _enabled(mode):
        raise ValueError("Reference answers are unavailable in this environment.")
    if mode == "mcp":
        result = asyncio.run(_call_tool(
            current_app.config["MCP_SERVER_URL"], "search_almanac_catalogue",
            {"query": question, "kind": "all", "limit": 20}))
        if result.get("is_error"):
            raise ValueError("The reference lookup could not be completed. Try again.")
        count = (result.get("structured_content") or {}).get("total", 0)
        return f"Found {count} matching references." if count else "No matching references found. Try a plant, pest or disease name.", result
    result = _rag_request("/rag/query", {"question": question, "sources": ["almanac"]})
    if result.get("error"):
        raise ValueError("The reference service could not answer. Please try again.")
    return result.get("answer") or "The saved references do not contain enough information to answer that.", result

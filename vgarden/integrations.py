"""Clients for the shared local MCP and RAG servers (Release 1), scoped to one
garden at a time.

The browser never talks to either server: the vgarden *backend* owns these
clients (see garden_integrations.py). Garden data is private per-owner, so both
clients are deliberately narrower than the almanac/health equivalents:

- ``McpToolClient.call`` only ever sends ``{"garden_id": <this garden's id>}`` —
  the caller supplies a tool name, never arguments, so a garden's owner can never
  point a tool call at someone else's garden.
- ``RagClient.ask`` always sends ``source_id=str(garden_id)``, so a question is
  only ever grounded in this one garden's indexed passages, never another
  owner's. See ai-services/rag-server/sources/vgarden.py.

Both integrations can be switched off with ``MCP_ENABLED`` / ``RAG_ENABLED`` —
CI runs that way — in which case the UI shows a clear "disabled" state instead
of a connection error.
"""

from __future__ import annotations

import asyncio
import logging
import time

import requests

logger = logging.getLogger(__name__)


class IntegrationDisabled(RuntimeError):
    """The integration is switched off by configuration."""


class IntegrationUnavailable(RuntimeError):
    """The shared server could not be reached or answered unexpectedly."""


# --------------------------------------------------------------------------- #
# MCP                                                                         #
# --------------------------------------------------------------------------- #

# The only tools this backend will ever ask the shared server to run. Both take
# only `garden_id`, which this backend always supplies itself from the
# authenticated route — never from client-supplied form/JSON input.
GARDEN_TOOLS = ("get_garden_snapshot", "list_garden_plantings")

TOOL_LABELS = {
    "get_garden_snapshot": "Garden snapshot (areas, containers, plantings)",
    "list_garden_plantings": "List plantings",
}


class McpToolClient:
    """Thin synchronous wrapper over the official MCP client, scoped to the
    Virtual Garden tools."""

    def __init__(self, target, *, enabled: bool = True, timeout: float = 60.0):
        self.target = target
        self.enabled = enabled
        self.timeout = timeout

    @property
    def url(self) -> str | None:
        return self.target if isinstance(self.target, str) else None

    def _require_enabled(self) -> None:
        if not self.enabled:
            raise IntegrationDisabled(
                "MCP is disabled for this service (MCP_ENABLED=false). No tool was run."
            )

    def _run(self, coroutine_factory):
        from mcp import Client

        async def go():
            async with Client(self.target, read_timeout_seconds=self.timeout) as client:
                return await coroutine_factory(client)

        try:
            return asyncio.run(go())
        except Exception as exc:  # noqa: BLE001 - the SDK raises grouped transport errors
            logger.warning("MCP server unavailable: %s", exc.__class__.__name__)
            raise IntegrationUnavailable(
                "The shared MCP server could not be reached. Start it with "
                "`python ai-services/mcp-server/server.py` and try again."
            ) from exc

    def list_tools(self) -> list[dict]:
        self._require_enabled()

        async def go(client):
            return (await client.list_tools()).tools

        tools = self._run(go)
        return [
            {
                "name": t.name,
                "description": (t.description or "").strip().split("\n")[0],
                "read_only": bool(t.annotations and t.annotations.read_only_hint),
                "vgarden": t.name in GARDEN_TOOLS,
            }
            for t in tools
        ]

    def call(self, tool: str, garden_id: int) -> dict:
        """Run one whitelisted, read-only Virtual Garden tool for one garden.

        ``garden_id`` always comes from the authenticated route, never client
        input — see the boundary note in the module docstring.
        """

        self._require_enabled()
        if tool not in GARDEN_TOOLS:
            raise ValueError(f"'{tool}' is not a Virtual Garden tool.")

        async def go(client):
            return await client.call_tool(tool, {"garden_id": garden_id})

        started = time.monotonic()
        result = self._run(go)
        text = " ".join(
            getattr(block, "text", "") for block in (result.content or []) if getattr(block, "text", "")
        ).strip()
        return {
            "tool": tool,
            "arguments": {"garden_id": garden_id},
            "is_error": bool(result.is_error),
            "structured_content": None if result.is_error else result.structured_content,
            "text": text,
            "duration_ms": int((time.monotonic() - started) * 1000),
        }


# --------------------------------------------------------------------------- #
# RAG                                                                         #
# --------------------------------------------------------------------------- #


class RagClient:
    def __init__(self, base_url: str, *, enabled: bool = True, timeout: float = 180.0):
        self.base_url = base_url.rstrip("/")
        self.enabled = enabled
        self.timeout = timeout

    def _require_enabled(self) -> None:
        if not self.enabled:
            raise IntegrationDisabled(
                "RAG is disabled for this service (RAG_ENABLED=false). No context was retrieved."
            )

    def _request(self, method: str, path: str, **kwargs) -> tuple[int, dict]:
        try:
            response = requests.request(
                method, f"{self.base_url}{path}", timeout=kwargs.pop("timeout", self.timeout), **kwargs
            )
            body = response.json()
        except (requests.RequestException, ValueError) as exc:
            logger.warning("RAG server unavailable: %s", exc.__class__.__name__)
            raise IntegrationUnavailable(
                "The shared RAG server could not be reached. Start it with "
                "`python ai-services/rag-server/app.py` and try again."
            ) from exc
        if not isinstance(body, dict):
            raise IntegrationUnavailable("The shared RAG server returned an unexpected response.")
        return response.status_code, body

    def status(self) -> dict:
        self._require_enabled()
        _, body = self._request("GET", "/healthz", timeout=5)
        return body

    def ask(self, question: str, *, garden_id: int) -> dict:
        """Ask a question grounded only in this one garden's indexed state.

        ``source_id=str(garden_id)`` is what keeps the answer from being
        grounded in another owner's garden: the vgarden RAG source indexes one
        document (and therefore one ``source_id``) per garden. See
        ai-services/rag-server/sources/vgarden.py.
        """

        self._require_enabled()
        payload = {"question": question, "sources": ["vgarden"], "source_id": str(garden_id)}
        code, body = self._request("POST", "/rag/query", json=payload)
        if code == 400:
            raise ValueError(body.get("error", "The RAG server rejected the question."))
        if code != 200:
            raise IntegrationUnavailable(
                body.get("error", f"The shared RAG server answered HTTP {code}.")
            )
        return body

    def sync_vgarden(self) -> dict:
        """Ask the RAG server to (re)index every garden's current state.

        There is no per-garden ingest endpoint — re-indexing is cheap and the
        shared contract (``POST /rag/ingest/<source>``) always replaces one
        whole source. Per-garden isolation happens at query time (``ask``
        above), not at ingest time.
        """

        self._require_enabled()
        code, body = self._request("POST", "/rag/ingest/vgarden")
        if code != 200:
            raise IntegrationUnavailable(
                body.get("error", f"The shared RAG server answered HTTP {code}.")
            )
        return body

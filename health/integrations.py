"""Clients for the shared local MCP and RAG servers (Release 1).

The browser never talks to either server: the health *backend* owns these
clients and exposes a small, whitelisted surface over them (see routes.py). Both
integrations can be switched off with ``MCP_ENABLED`` / ``RAG_ENABLED`` — CI runs
that way — in which case the UI shows a clear "disabled" state instead of a
connection error.
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

STATUSES = ("healthy", "at_risk", "unhealthy", "unknown")

# The only tools this backend will ask the shared server to run, and the only
# arguments it will forward for each. Anything else is rejected before a request
# leaves the service — the tool boundary is enforced here *and* on the server.
HEALTH_TOOLS: dict[str, dict[str, str]] = {
    "health_service_status": {},
    "list_health_assessments": {"plant_ref": "str", "status": "status", "limit": "int"},
    "get_health_assessment": {"assessment_id": "int"},
    "summarise_plant_health_history": {"plant_ref": "str!", "limit": "int"},
    "assess_plant_health": {"description": "str!", "plant_ref": "str"},
}

TOOL_LABELS = {
    "health_service_status": "Service status",
    "list_health_assessments": "List assessments",
    "get_health_assessment": "Get one assessment",
    "summarise_plant_health_history": "Summarise a plant's history",
    "assess_plant_health": "Assess a plant (text only, creates a record)",
}


def coerce_tool_args(tool: str, raw) -> dict:
    """Validate and coerce user-supplied arguments for a whitelisted health tool."""

    spec = HEALTH_TOOLS.get(tool)
    if spec is None:
        raise ValueError(
            f"Unknown or non-health tool '{tool}'. Allowed: {', '.join(sorted(HEALTH_TOOLS))}."
        )
    args: dict = {}
    for name, kind in spec.items():
        required = kind.endswith("!")
        kind = kind.rstrip("!")
        value = raw.get(name)
        if value is None or (isinstance(value, str) and not value.strip()):
            if required:
                raise ValueError(f"'{name}' is required for {tool}.")
            continue
        if kind == "int":
            try:
                value = int(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"'{name}' must be a whole number.") from exc
        elif kind == "status":
            value = str(value).strip().lower()
            if value not in STATUSES:
                raise ValueError(f"'{name}' must be one of: {', '.join(STATUSES)}.")
        else:
            value = str(value).strip()
        args[name] = value
    return args


class McpToolClient:
    """Thin synchronous wrapper over the official MCP client.

    ``target`` is the shared server's streamable-http URL (``…/mcp``). Tests may
    pass an in-process ``MCPServer`` object instead.
    """

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
                "health": t.name in HEALTH_TOOLS,
            }
            for t in tools
        ]

    def call(self, tool: str, arguments: dict) -> dict:
        """Run one whitelisted tool; returns a display-ready structured result."""

        self._require_enabled()
        if tool not in HEALTH_TOOLS:
            raise ValueError(f"'{tool}' is not a Plant Health tool.")

        async def go(client):
            return await client.call_tool(tool, arguments)

        started = time.monotonic()
        result = self._run(go)
        text = " ".join(
            getattr(block, "text", "") for block in (result.content or []) if getattr(block, "text", "")
        ).strip()
        return {
            "tool": tool,
            "arguments": arguments,
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

    def ask(self, question: str, *, sources=("health",), top_k: int | None = None) -> dict:
        self._require_enabled()
        payload = {"question": question, "sources": list(sources)}
        if top_k is not None:
            payload["top_k"] = top_k
        code, body = self._request("POST", "/rag/query", json=payload)
        if code == 400:
            raise ValueError(body.get("error", "The RAG server rejected the question."))
        if code != 200:
            raise IntegrationUnavailable(
                body.get("error", f"The shared RAG server answered HTTP {code}.")
            )
        return body

    def sync_health(self) -> dict:
        """Ask the RAG server to (re)index this service's assessments."""

        self._require_enabled()
        code, body = self._request("POST", "/rag/ingest/health")
        if code != 200:
            raise IntegrationUnavailable(
                body.get("error", f"The shared RAG server answered HTTP {code}.")
            )
        return body

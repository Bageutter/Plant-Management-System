"""Helpers shared by every tool group: the enable switch, honest stub errors, and
the one HTTP client tools are allowed to use to reach a feature service."""

from __future__ import annotations

import json

import httpx
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

READ_ONLY = ToolAnnotations(
    read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False
)
# Creates a record in the owning service but never edits or deletes one.
CREATES_RECORD = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False
)

DISABLED_MESSAGE = (
    "MCP tool access is disabled by the server configuration (MCP_ENABLED=false). "
    "Tool discovery still works; no feature data was read."
)


def guard(settings) -> None:
    """Refuse every tool call while the server is switched off (e.g. during CI)."""

    if not settings.enabled:
        raise ToolError(DISABLED_MESSAGE)


def not_implemented(tool: str, feature: str, tracking: str) -> ToolError:
    """The honest answer for a registered-but-unbuilt tool.

    The tool stays discoverable with its full input/output schema so client
    integrations can be written against the contract, but calling it never
    fabricates a result.
    """

    return ToolError(
        f"{tool} is not implemented in the shared MCP server yet: the {feature} "
        f"integration is tracked in {tracking}. No data was returned."
    )


class FeatureClient:
    """Fixed-origin HTTP client for one feature service's *public* API.

    Only tool code chooses the path; tool arguments can never supply an origin,
    method or path. Redirects are not followed, the environment's proxy settings
    are ignored, and every failure becomes a ``ToolError`` whose text is safe to
    show to an AI host (no internal exception details).

    ``headers`` is tool-code-supplied only (never from tool arguments) — used by
    the Virtual Garden tools to send the shared service-token bearer auth that
    feature's private, owner-scoped endpoints require (see tools/vgarden.py).
    """

    def __init__(self, name: str, base_url: str, timeout: float, *, transport=None):
        self.name = name
        self.base_url = base_url.rstrip("/") + "/"
        self.timeout = timeout
        self.transport = transport

    def get(self, path: str, *, ok=(200,), timeout: float | None = None, headers=None, **params):
        return self._request("GET", path, params=params or None, ok=ok, timeout=timeout, headers=headers)

    def post(self, path: str, body: dict, *, ok=(200, 201), timeout: float | None = None, headers=None):
        return self._request("POST", path, json=body, ok=ok, timeout=timeout, headers=headers)

    def _request(self, method, path, *, params=None, json=None, ok, timeout, headers=None):
        try:
            with httpx.Client(
                base_url=self.base_url,
                timeout=timeout or self.timeout,
                follow_redirects=False,
                trust_env=False,
                transport=self.transport,
            ) as client:
                response = client.request(method, path.lstrip("/"), params=params, json=json, headers=headers)
        except httpx.HTTPError:
            raise ToolError(
                f"The {self.name} service is unavailable or timed out at {self.base_url}. "
                "Start the application stack and try again."
            ) from None

        try:
            payload = response.json()
        except ValueError:
            payload = None

        if response.status_code in ok:
            if payload is None:
                raise ToolError(f"The {self.name} service returned a non-JSON response.")
            return payload

        detail = payload.get("error") if isinstance(payload, dict) else None
        if response.status_code == 404:
            raise ToolError(detail or f"The requested {self.name} record was not found.")
        if response.status_code == 400:
            raise ToolError(detail or f"The {self.name} service rejected the request.")
        if response.status_code == 503:
            raise ToolError(
                detail or f"The {self.name} service's local AI model is currently unavailable."
            )
        raise ToolError(
            f"The {self.name} service returned HTTP {response.status_code}"
            + (f": {detail}" if detail else ".")
        )


def as_json(value) -> str:
    return json.dumps(value, ensure_ascii=False)

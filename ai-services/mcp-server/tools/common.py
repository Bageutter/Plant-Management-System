"""Helpers shared by every tool group: the enable switch and honest stub errors."""

from __future__ import annotations

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

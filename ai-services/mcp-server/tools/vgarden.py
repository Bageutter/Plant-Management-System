"""Virtual Garden tools — registered stubs.

The Virtual Garden is the source of truth for garden state, and its pages are
owner-scoped. Exposing that state over the shared MCP server needs an
inter-service read endpoint on the vgarden side (an authenticated, read-only
snapshot). Until that exists these tools are honest stubs.
"""

from __future__ import annotations

from mcp.server import MCPServer

from tools.common import READ_ONLY, guard, not_implemented
from tools.schemas import GardenSnapshot, PlantingList, RecordId

FEATURE = "Virtual Garden"
TRACKING = "GitHub issue #42 (Bageutter/Plant-Management-System)"


def register(server: MCPServer, settings) -> None:
    @server.tool(annotations=READ_ONLY)
    def get_garden_snapshot(garden_id: RecordId) -> GardenSnapshot:
        """Read one garden's areas, containers and plantings as a compact snapshot."""
        guard(settings)
        raise not_implemented("get_garden_snapshot", FEATURE, TRACKING)

    @server.tool(annotations=READ_ONLY)
    def list_garden_plantings(garden_id: RecordId) -> PlantingList:
        """List the plantings recorded in one garden."""
        guard(settings)
        raise not_implemented("list_garden_plantings", FEATURE, TRACKING)

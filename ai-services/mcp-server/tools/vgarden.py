"""Read-only Virtual Garden tools on the shared server.

Garden state is private per-owner (unlike the public Almanac catalogue or Plant
Health assessments), so — unlike ``tools/almanac.py`` and ``tools/health.py`` —
these calls carry the shared service-token bearer auth that vgarden's snapshot
endpoints require (``require_service_token`` in ``vgarden/routes.py``). Tools
still reach vgarden only through its public HTTP API via the proxy, never its
database, and the token travels as a header the tool arguments can never set —
see the boundary note on ``tools.common.FeatureClient``.
"""

from __future__ import annotations

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import ValidationError

from tools.common import READ_ONLY, FeatureClient, guard
from tools.schemas import GardenSnapshot, PlantingList, RecordId


def register(server: MCPServer, settings, *, transport=None) -> None:
    api = FeatureClient("Virtual Garden", settings.vgarden_url, settings.timeout, transport=transport)
    auth_headers = {"Authorization": f"Bearer {settings.vgarden_service_token}"}

    @server.tool(annotations=READ_ONLY)
    def get_garden_snapshot(garden_id: RecordId) -> GardenSnapshot:
        """Read one garden's areas, containers and plantings as a compact snapshot."""
        guard(settings)
        payload = api.get(f"gardens/{garden_id}/snapshot", headers=auth_headers)
        try:
            return GardenSnapshot.model_validate(payload)
        except ValidationError:
            raise ToolError("The Virtual Garden service returned an unexpected snapshot.") from None

    @server.tool(annotations=READ_ONLY)
    def list_garden_plantings(garden_id: RecordId) -> PlantingList:
        """List the plantings recorded in one garden."""
        guard(settings)
        payload = api.get(f"gardens/{garden_id}/plantings", headers=auth_headers)
        try:
            return PlantingList.model_validate(payload)
        except ValidationError:
            raise ToolError("The Virtual Garden service returned an unexpected planting list.") from None

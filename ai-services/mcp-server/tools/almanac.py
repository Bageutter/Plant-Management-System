"""Read-only Almanac tools on the shared server, using the public catalogue API."""

from __future__ import annotations

from typing import Literal

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import ValidationError

from tools.common import READ_ONLY, FeatureClient, guard
from tools.schemas import AlmanacPlantDetail, AlmanacSearchPage, Limit, Query, Slug

Kind = Literal["all", "plant", "pest", "disease"]


def register(server: MCPServer, settings, *, transport=None) -> None:
    api = FeatureClient("Plant Almanac", settings.almanac_url, settings.timeout, transport=transport)

    @server.tool(annotations=READ_ONLY)
    def search_almanac_catalogue(
        query: Query = "", kind: Kind = "all", limit: Limit = 20
    ) -> AlmanacSearchPage:
        """Find plants, pests and diseases in the Plant Almanac by name."""
        guard(settings)
        payload = api.get("api/catalogue", q=query, kind=kind, limit=limit)
        try:
            return AlmanacSearchPage.model_validate(payload)
        except ValidationError:
            raise ToolError("The Plant Almanac service returned an unexpected search result.") from None

    @server.tool(annotations=READ_ONLY)
    def get_almanac_plant(slug: Slug) -> AlmanacPlantDetail:
        """Read a plant reference: growing facts, companions and linked problems."""
        guard(settings)
        payload = api.get(f"api/catalogue/plant/{slug}")
        try:
            return AlmanacPlantDetail.model_validate(payload)
        except ValidationError:
            raise ToolError("The Plant Almanac service returned an unexpected plant result.") from None

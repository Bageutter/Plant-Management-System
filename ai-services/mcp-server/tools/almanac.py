"""Plant Almanac tools — registered stubs.

The Almanac already has a working standalone MCP adapter in PR #36
(``almanac/mcp_server.py``). These stubs reserve the same tool names and result
shapes on the *shared* server so that adapter can be folded in without changing
any client. Until then every call returns a "not implemented" tool error.
"""

from __future__ import annotations

from typing import Literal

from mcp.server import MCPServer

from tools.common import READ_ONLY, guard, not_implemented
from tools.schemas import AlmanacPlantDetail, AlmanacSearchPage, Limit, Query, Slug

FEATURE = "Plant Almanac"
TRACKING = "the Almanac MCP tracking issue (see ai-services/mcp-server/README.md)"

Kind = Literal["all", "plant", "pest", "disease"]


def register(server: MCPServer, settings) -> None:
    @server.tool(annotations=READ_ONLY)
    def search_almanac_catalogue(
        query: Query = "", kind: Kind = "all", limit: Limit = 20
    ) -> AlmanacSearchPage:
        """Find plants, pests and diseases in the Plant Almanac by name."""
        guard(settings)
        raise not_implemented("search_almanac_catalogue", FEATURE, TRACKING)

    @server.tool(annotations=READ_ONLY)
    def get_almanac_plant(slug: Slug) -> AlmanacPlantDetail:
        """Read a plant reference: growing facts, companions and linked problems."""
        guard(settings)
        raise not_implemented("get_almanac_plant", FEATURE, TRACKING)

"""Run a small real MCP discovery and catalogue retrieval demonstration."""

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys

from mcp import Client
from mcp.client.stdio import StdioServerParameters


async def demonstrate(url=None):
    target = url or StdioServerParameters(
        command=sys.executable,
        args=[str(Path(__file__).with_name("mcp_server.py"))],
        env={
            "ALMANAC_BASE_URL": os.environ.get("ALMANAC_BASE_URL", "http://127.0.0.1:3000/almanac")
        },
    )
    async with Client(target, read_timeout_seconds=15) as client:
        tools = [tool.name for tool in (await client.list_tools()).tools]
        print("Discovered tools:", ", ".join(tools))
        for kind, query in [
            ("plant", "lettuce"),
            ("pest", "Aphids"),
            ("disease", "Powdery mildew"),
        ]:
            result = await client.call_tool("search_catalogue", {"query": query, "kind": kind})
            if result.is_error:
                raise RuntimeError(result.content[0].text)
            items = result.structured_content["items"]
            if not items:
                print(f"{query}: not recorded. Run the documented sample seed commands.")
                continue
            exact = next(
                (item for item in items if item["name"].casefold() == query.casefold()), items[0]
            )
            name = "get_plant" if kind == "plant" else "get_problem"
            args = (
                {"slug": exact["key"]}
                if kind == "plant"
                else {"kind": kind, "record_id": exact["id"]}
            )
            detail = await client.call_tool(name, args)
            if detail.is_error:
                raise RuntimeError(detail.content[0].text)
            data = detail.structured_content
            print(
                json.dumps(
                    {
                        "name": data["name"],
                        "uri": data["uri"],
                        "path": data["path"],
                        "estimated_fields": data.get("record", {}).get("estimated_fields", []),
                        "guide_available": data.get("guide_available"),
                        "sources": (data.get("guide") or {}).get("sources", []),
                    },
                    indent=2,
                )
            )
        print("Resources:", [str(item.uri) for item in (await client.list_resources()).resources])
        print("Prompts:", [item.name for item in (await client.list_prompts()).prompts])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url", help="An already running MCP HTTP endpoint, e.g. http://127.0.0.1:5104/mcp"
    )
    options = parser.parse_args()
    asyncio.run(demonstrate(options.url))

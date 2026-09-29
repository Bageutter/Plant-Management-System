"""Collect actual MCP invocations for the web explorer and review pipeline."""

import asyncio
from datetime import datetime, timezone
import os
from pathlib import Path
import sys
import time
import uuid

from mcp import Client
from mcp.client.stdio import StdioServerParameters


BOUNDARIES = {
    "search_catalogue": "Find recorded names and keys; does not infer missing species or diagnoses.",
    "get_plant": "Read growing facts and estimates; does not edit plants or promise yields.",
    "get_problem": "Read guides and associations; does not diagnose a plant or prescribe doses.",
}


def now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def stdio_target(base_url):
    return StdioServerParameters(
        command=sys.executable,
        args=[str(Path(__file__).with_name("mcp_server.py"))],
        env={"ALMANAC_BASE_URL": base_url, "MCP_ENABLED": os.environ.get("MCP_ENABLED", "true")},
    )


class EvidenceSession:
    def __init__(self, client):
        self.client = client
        self.report = {
            "schema_version": 1,
            "run_id": str(uuid.uuid4()),
            "started_at": now(),
            "transport": "stdio",
            "tools": [],
            "calls": [],
            "human_review": {"decision": "pending", "reason": "No human decision recorded."},
        }

    async def discover(self):
        tools = (await self.client.list_tools()).tools
        self.report["tools"] = [tool.model_dump(mode="json", by_alias=True) for tool in tools]
        if {tool.name for tool in tools} != set(BOUNDARIES):
            raise ValueError("Discovered tools do not match the three allowed Almanac tools.")

    async def invoke(self, tool, arguments):
        if tool not in BOUNDARIES:
            raise ValueError("Choose one of the three Almanac tools.")
        started, clock = now(), time.monotonic()
        try:
            result = await self.client.call_tool(tool, arguments)
            entry = {
                "tool": tool,
                "input": arguments,
                "started_at": started,
                "duration_ms": round((time.monotonic() - clock) * 1000),
                "is_error": result.is_error,
                "output": result.structured_content,
                "message": "\n".join(getattr(item, "text", "") for item in result.content)
                if result.is_error
                else None,
            }
        except Exception:
            entry = {
                "tool": tool,
                "input": arguments,
                "started_at": started,
                "duration_ms": round((time.monotonic() - clock) * 1000),
                "is_error": True,
                "output": None,
                "message": "MCP connection failed or timed out. Check the configured Almanac service.",
            }
        self.report["calls"].append(entry)
        return entry


async def execute(base_url, tool, arguments):
    async with Client(stdio_target(base_url), read_timeout_seconds=15) as client:
        session = EvidenceSession(client)
        await session.discover()
        await session.invoke(tool, arguments)
        return session.report


async def _collect(base_url):
    """Exercise all three tools with discovered sample IDs; capture failures too."""
    async with Client(stdio_target(base_url), read_timeout_seconds=15) as client:
        session = EvidenceSession(client)
        await session.discover()
        samples = []
        for kind, query in (
            ("plant", "Lettuce"),
            ("pest", "Aphids"),
            ("disease", "Powdery mildew"),
        ):
            found = await session.invoke("search_catalogue", {"query": query, "kind": kind})
            items = (found["output"] or {}).get("items", [])
            exact = next(
                (item for item in items if item["name"].casefold() == query.casefold()), None
            )
            if not exact:
                continue
            samples.append(kind)
            if kind == "plant":
                await session.invoke("get_plant", {"slug": exact["key"]})
            else:
                await session.invoke("get_problem", {"kind": kind, "record_id": exact["id"]})
        succeeded = {call["tool"] for call in session.report["calls"] if not call["is_error"]}
        session.report["validation"] = {
            "sample_records_found": set(samples) == {"plant", "pest", "disease"},
            "all_tools_executed": succeeded == set(BOUNDARIES),
            "all_calls_succeeded": all(not call["is_error"] for call in session.report["calls"]),
        }
        session.report["finished_at"] = now()
        return session.report


async def collect(base_url):
    try:
        return await asyncio.wait_for(_collect(base_url), timeout=150)
    except Exception:
        report = EvidenceSession(None).report
        report.update(
            {
                "finished_at": now(),
                "validation": {"collection_completed": False},
                "error": "MCP discovery or collection failed. No completed run evidence is available.",
            }
        )
        return report


def run_tool(base_url, tool, arguments):
    async def bounded():
        return await asyncio.wait_for(execute(base_url, tool, arguments), timeout=30)

    return asyncio.run(bounded())

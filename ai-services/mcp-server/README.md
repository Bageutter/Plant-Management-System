# Shared MCP server

One **local, non-containerised** [MCP](https://modelcontextprotocol.io) server for the
whole Plant Management System. Feature backends (Plant Health, Plant Almanac, Virtual
Garden) call it from their own API routes, so their frontends reach MCP *through* the
backend — the Release 1 requirement. It is never a `docker compose` service.

Design and boundaries: [`docs/ai/mcp-rag-design.md`](../../docs/ai/mcp-rag-design.md).

```text
feature UI ─► feature backend/API ─► shared MCP server (localhost:5105/mcp) ─► feature public HTTP API (:3000)
```

## Run it

From the repository root (Python 3.12 recommended; the pinned SDK needs ≥ 3.10):

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r ai-services/mcp-server/requirements-dev.txt   # Windows
# .venv/bin/python -m pip install -r ai-services/mcp-server/requirements-dev.txt    # macOS / Linux

python ai-services/mcp-server/server.py
# -> http://127.0.0.1:5105/mcp   (streamable-http, stateless, JSON responses)
# -> http://127.0.0.1:5105/healthz
```

For a desktop MCP host use `--transport stdio`:

```json
{
  "mcpServers": {
    "plant-management-system": {
      "command": "/absolute/path/.venv/bin/python",
      "args": ["/absolute/path/ai-services/mcp-server/server.py", "--transport", "stdio"]
    }
  }
}
```

### Configuration

| Env | Default | Purpose |
| --- | --- | --- |
| `MCP_ENABLED` | `true` | `false` keeps discovery working but refuses every tool call. CI sets this. |
| `MCP_HOST` / `MCP_PORT` | `127.0.0.1` / `5105` | Listener. Containers reach it as `host.docker.internal:5105`. |
| `MCP_ALLOWED_HOSTS` | `127.0.0.1:*,localhost:*,host.docker.internal:*` | `Host` header allow-list (DNS-rebinding protection stays on) |
| `HEALTH_SERVICE_URL` | `http://127.0.0.1:3000/health` | Plant Health public API, via the proxy |
| `ALMANAC_SERVICE_URL` | `http://127.0.0.1:3000/almanac` | reserved for the Almanac tools |
| `VGARDEN_SERVICE_URL` | `http://127.0.0.1:3000/vgarden` | reserved for the Virtual Garden tools |
| `SERVICE_TIMEOUT` | `10` | seconds per outbound call |
| `ASSESS_TIMEOUT` | `200` | seconds allowed for `assess_plant_health` (it runs the vision model) |

## Registered tools

| Tool | Feature | Status | Boundary |
| --- | --- | --- | --- |
| `health_service_status` | Plant Health | **implemented** | read-only |
| `list_health_assessments` | Plant Health | **implemented** | read-only, no image bytes; filters `plant_ref`, `status`, `limit ≤ 50` |
| `get_health_assessment` | Plant Health | **implemented** | read-only |
| `summarise_plant_health_history` | Plant Health | **implemented** | read-only, aggregated in code (no model call) |
| `assess_plant_health` | Plant Health | **implemented** | **creates** one record via the health service's local model; text only |
| `search_almanac_catalogue` | Plant Almanac | stub — issue #41 | read-only |
| `get_almanac_plant` | Plant Almanac | stub — issue #41 | read-only |
| `get_garden_snapshot` | Virtual Garden | stub — issue #42 | read-only |
| `list_garden_plantings` | Virtual Garden | stub — issue #42 | read-only |

Resources: `pms://about`, `health://assessments/{assessment_id}`.
Prompt: `review_plant_health_history(plant_ref)`.

Every tool has validated inputs and a pinned `outputSchema`. A **stub** is fully
discoverable but returns a tool error that says it is not implemented — it never
fabricates data. Tools cannot supply a URL, HTTP method, path or SQL; each tool calls a
fixed endpoint on the configured feature origin.

## Validate from a terminal

```bash
curl -s http://127.0.0.1:5105/healthz
```

```bash
python - <<'EOF'
import asyncio
from mcp import Client

async def main():
    async with Client("http://127.0.0.1:5105/mcp") as client:
        print([t.name for t in (await client.list_tools()).tools])
        result = await client.call_tool("list_health_assessments", {"limit": 3})
        print(result.is_error, result.structured_content or result.content[0].text)

asyncio.run(main())
EOF
```

## Tests

```bash
cd ai-services/mcp-server
python -m pytest -q
```

The suite covers discovery (names, schemas, annotations, resources, prompt), input
validation, the `MCP_ENABLED=false` switch, honest stub errors, a real
streamable-http listener including the `Host` header check, and every Plant Health
tool against a fake health API (filters, aggregation, 404/503/redirect/offline
handling). No model or feature service is required.

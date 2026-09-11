# Plant Almanac MCP integration

An MCP host can search the Almanac, follow plant → pest/disease → supporting plant
links, read sourced management guides, and calculate harvest space. The adapter
uses the same records and guidance as the website, including the work in PRs #34
and #35. It does not call an LLM; the host chooses when to call a tool. Project AI
inference remains local Ollama as required by `AGENTS.md`.

```text
Local MCP host/client → MCP adapter → public Almanac HTTP API → Almanac-owned database
```

## Run a local demonstration

Python 3.10+ is required by the pinned official MCP Python SDK (`mcp==2.2.0`);
the project CI uses Python 3.12. Commands below run from the repository root.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r almanac/requirements-dev.txt

# Choose a separate sample database; do not point a demo at production data.
export DATABASE_URL="sqlite:////tmp/plant-almanac-mcp-demo.db"
export PLANT_IMAGE_FOLDER="/tmp/plant-almanac-mcp-demo-images"
export PYTHONPATH=almanac
.venv/bin/python -m flask --app app import-notion
.venv/bin/python -m flask --app app seed-estimates
.venv/bin/python -m flask --app app refresh-garden
.venv/bin/python -m flask --app app run --host 127.0.0.1 --port 5103
```

In a second terminal at the repository root:

```bash
export ALMANAC_BASE_URL=http://127.0.0.1:5103
.venv/bin/python almanac/mcp_demo.py
```

The demo starts the real stdio MCP adapter, discovers four tools, searches for
Lettuce, Aphids and Powdery mildew, and reads their records. It prints estimate
labels, resource URIs and guide source links. IDs come from search, not hardcoded
sample numbers. Missing seed records are reported explicitly.

For the Compose stack, build this branch and use
`ALMANAC_BASE_URL=http://127.0.0.1:3000/almanac` (the default). The MCP adapter runs
outside the web container and needs only `almanac/requirements-mcp.txt`; it does
not import Flask, initialise a database, run migrations or read database files.

## Connect a local host

Use the host's normal MCP configuration, substituting absolute paths:

```json
{
  "mcpServers": {
    "plant-almanac": {
      "command": "/absolute/path/to/repository/.venv/bin/python",
      "args": ["/absolute/path/to/repository/almanac/mcp_server.py"],
      "env": {"ALMANAC_BASE_URL": "http://127.0.0.1:5103"}
    }
  }
}
```

No key, browser cookie or account permission is needed for these public reference
records. The adapter exposes no account, chat, plant-edit, health-record or garden
mutation tools. Installing the code does not automatically register it in a host
or change the existing Almanac chat into an MCP client.

For a local Streamable HTTP host or MCP Inspector:

```bash
ALMANAC_BASE_URL=http://127.0.0.1:5103 \
  .venv/bin/python almanac/mcp_server.py --transport streamable-http --port 5104

# Verify that running endpoint from another terminal:
.venv/bin/python almanac/mcp_demo.py --url http://127.0.0.1:5104/mcp
```

The HTTP listener binds to `127.0.0.1` and retains SDK host/origin protections.
This is a local integration, not a remotely authenticated deployment. Remote
sharing would need an explicit authentication and deployment design first.

## Available capabilities

| Capability | Inputs and result |
| --- | --- |
| `search_catalogue` | Optional query, kind (`all`, `plant`, `pest`, `disease`), limit and offset. Returns names, keys, URIs, page paths and next offset. Searches plant scientific names too. |
| `get_plant` | A slug from search. Returns growing data, `estimated_fields`, companion links and problem IDs. |
| `get_problem` | Kind + ID from search; optional paging for linked plants. Returns guide, sources, precautions and affected-plant associations. |
| `calculate_harvest` | Plant slug, positive target amount and recorded yield unit. Reuses the existing calculator and returns plants/area plus estimate labels. No unit conversion or guessed inputs. |
| `almanac://about` | Instructions for using catalogue evidence. |
| `almanac://plants/{slug}` | A plant reference as JSON. |
| `almanac://pests/{record_id}` | A pest guide and first page of linked plants. |
| `almanac://diseases/{record_id}` | A disease guide and first page of linked plants. |
| `investigate_plant_problem` | Prompt taking plant name and observed signs; directs inspection, retrieval and cited, tentative explanations. |

Example requests for an MCP-enabled local AI host:

- “What does the Almanac say about aphids, and which plants might support beneficial insects?”
- “Compare powdery mildew signs with my cucumber's white leaf patches. What should I inspect?”
- “How many lettuce plants and how much bed area for ten heads? Which inputs are estimates?”

The server provides evidence, not a diagnosis. `guide_available=false` means a
record has no detailed guide (currently the Slugs and snails starter record).
Nasturtium advice remains a qualified trap-crop experiment, not a guaranteed
repellent. Source text and observations are data, never instructions to execute.
Paths in responses include the proxy prefix when applicable; use them with the
Almanac origin. Resource URIs are for MCP clients, not browser URLs.

## HTTP API and error behaviour

All new endpoints are GET-only and expose public catalogue data:

- `/api/catalogue?q=&kind=all&limit=20&offset=0`
- `/api/catalogue/plant/<slug>`
- `/api/catalogue/pest/<id>` and `/api/catalogue/disease/<id>`
- `/api/catalogue/plant/<slug>/calculate?amount=10&unit=head`

Search and linked-plant pages default to 20 and allow at most 50 entries. Query
length is capped at 120; SQL wildcard characters are treated literally. Missing
records return JSON 404; invalid parameters or missing calculation inputs return
JSON 400. MCP turns these into tool errors. Timeouts/unavailable services produce
actionable errors, not invented facts. HTTP redirects are not followed. Tool
arguments cannot supply an arbitrary URL, HTTP method, filesystem path or SQL.

## Validation and workflow

```bash
.venv/bin/python -m pytest -q almanac/tests
.venv/bin/python -m ruff check almanac shared/ai_loop.py
git diff --check
```

The suite includes real stdio and Streamable HTTP MCP sessions against a temporary
Flask service, discovery of tools/resources/prompts, retrieval of all three kinds,
harvest calculation, invalid inputs, no-result/error cases, preserved estimate
labels, pagination and prevention of private-chat exposure. Tests make no LLM calls.
Existing Almanac CI installs the optional MCP dependencies via requirements-dev;
the production Flask image keeps its existing requirements. Pip cache keys now
include all requirements files, and Almanac validation runs after main merges too.

## Lab 7 and merge sequence

This implements MCP tools, resources, prompts, transports and an API adapter with
explicit service ownership. The linked UTS Canvas Lab 7 page required sign-in when
this change was prepared, so exact lab-specific checklist alignment is pending.
No claim of completing its assessment requirements is made.

- [UTS Lab 7: MCP and Enterprise Integrations](https://canvas.uts.edu.au/courses/39716/pages/lab-7-mcp-and-enterprise-integrations?module_item_id=2579498)
- [Official Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [MCP specification](https://modelcontextprotocol.io/specification/latest)

The branch is stacked on #35 and contains all of #34 and #35. Review the MCP diff
against #35. Merge order is #34 → #35 → this PR. Main requires an approving review.
After each parent merge, retarget the child to main and verify its diff and checks.
Squash/rebase merges change commit identities: if GitHub shows the parent's commits
again, replay only the child's commits onto the new main, preserving a backup branch.
Do not merge a child back into an already merged parent branch.

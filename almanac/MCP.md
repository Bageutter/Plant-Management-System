# Plant Almanac MCP integration

An MCP host can search the Almanac, follow plant → pest/disease → supporting plant
links, and read sourced management guides. The adapter
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
export MCP_ALMANAC_BASE_URL=http://127.0.0.1:5103
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

The demo starts the real stdio MCP adapter, discovers three tools, searches for
Lettuce, Aphids and Powdery mildew, and reads their records. It prints estimate
labels, resource URIs and guide source links. IDs come from search, not hardcoded
sample numbers. Missing seed records are reported explicitly.

Open http://127.0.0.1:5103/tools for the **Explore with tools** page. Choose a tool,
enter its inputs, run a lookup and expand **View evidence**. Turning off the checkbox
prevents calls; `MCP_ENABLED=false` disables calls in the web service and adapter.
Set that flag in each independently launched process. Discovery remains available;
public website/API reads remain available. This is an operational switch, not authorization.
The page uses real stdio MCP, not a simulated HTTP-only tool response. It does not
automatically send catalogue data to an LLM or change the existing chat.

For the Compose stack, build this branch and use
`ALMANAC_BASE_URL=http://127.0.0.1:3000/almanac` (the default). The MCP adapter runs
outside the web container and needs only `almanac/requirements-mcp.txt`; it does
not import Flask, initialise a database, run migrations or read database files.
The web explorer also installs these dependencies in its image. Its fixed internal
target defaults to `MCP_ALMANAC_BASE_URL=http://127.0.0.1:5000`, appropriate inside
the Almanac container. Use concurrent/threaded web workers because the child adapter
calls the same service; the current Flask container runs threaded. Tool users cannot
override that URL. Each web lookup launches one short-lived adapter (30-second total
deadline); a remotely shared/high-volume service would need authentication and
rate/concurrency limits before deployment.

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

The scope is plants, pests and diseases. Harvest-to-space planning is removed:
there is no calculator tool, form or HTTP endpoint. Existing descriptive yield
and spacing records remain intact; tools do not derive planting density or bed area.

| Capability | Inputs and result |
| --- | --- |
| `search_catalogue` | Optional query, kind (`all`, `plant`, `pest`, `disease`), limit and offset. Returns names, keys, URIs, page paths and next offset. Searches plant scientific names too. |
| `get_plant` | A slug from search. Returns growing data, `estimated_fields`, companion links and problem IDs. |
| `get_problem` | Kind + ID from search; optional paging for linked plants. Returns guide, sources, precautions and affected-plant associations. |
| `almanac://about` | Instructions for using catalogue evidence. |
| `almanac://plants/{slug}` | A plant reference as JSON. |
| `almanac://pests/{record_id}` | A pest guide and first page of linked plants. |
| `almanac://diseases/{record_id}` | A disease guide and first page of linked plants. |
| `investigate_plant_problem` | Prompt taking plant name and observed signs; directs inspection, retrieval and cited, tentative explanations. |

Example requests for an MCP-enabled local AI host:

- “What does the Almanac say about aphids, and which plants might support beneficial insects?”
- “Compare powdery mildew signs with my cucumber's white leaf patches. What should I inspect?”
- “What growing facts are recorded for lettuce, and which fields are labelled estimates?”

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

Search and linked-plant pages default to 20 and allow at most 50 entries. Query
length is capped at 120; SQL wildcard characters are treated literally. Missing
records return JSON 404; invalid parameters return
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
retired-calculator rejection, invalid inputs, no-result/error cases, preserved estimate
labels, pagination and prevention of private-chat exposure. Tests make no LLM calls.
Almanac runtime and development requirements include the pinned MCP dependencies.
Pip cache keys include all requirements files, and validation runs after main merges
too. CI uploads `almanac-mcp-evidence` from actual test invocations for 14 days;
these artifacts explicitly say model review was not run. CI needs no Ollama or model downloads.

## Execute → capture → review → improve

```bash
# Repeatable evidence only (all three tools, three catalogue kinds):
ALMANAC_BASE_URL=http://127.0.0.1:5103 .venv/bin/python almanac/mcp_review.py

# Lab-style local proposer + reviewer, through the existing development pipeline:
ALMANAC_BASE_URL=http://127.0.0.1:5103 .venv/bin/python tools/ai-dev/pipeline.py --scope mcp

# Equivalent direct command, with optional explicit models:
.venv/bin/python almanac/mcp_review.py --base-url http://127.0.0.1:5103 --review \
  --proposer qwen2.5:0.5b --reviewer llama3.1:8b
```

The three sample records must be seeded first. The collector discovers schemas and
IDs, executes six real calls covering all three tools, and records inputs, results,
errors, timestamps and durations. Missing samples, tool failures, discovery failures
and invalid model responses produce non-success status; absence is never a pass.
Each UUID run under ignored `.ai-dev-runs/mcp/` contains `evidence.json`,
`run-report.md`, `boundary-analysis.md`, `tool-review.md`, and `integration-report.md`.
Runs never overwrite previous evidence. Reports contain public catalogue data only;
inspect before sharing, particularly if using a custom catalogue.

Optional review uses installed **local Ollama** models only, temperature zero and
validated JSON schemas. The proposer receives a compact set of actual output fields;
the reviewer compares that interpretation to the same evidence and tool boundaries.
At most two proposal/review attempts run; each model request has a 120-second timeout.
The full original outputs stay in the evidence file. No model downloads or automatic
code edits occur. Unavailable models, invalid JSON, invented evidence IDs, excessive
summary length, guide-availability claims that contradict actual results, and
unresolved revisions are recorded, not silently approved. See
[the measured Lab 7 improvement](MCP_LAB7_EVIDENCE.md) for a real small-model failure
and the resulting safeguards. The existing project's `qwen3:4b-instruct` is also
supported through `--proposer` when installed locally.

Model approval is advisory. Human review stays **pending**, even after both models
agree. Review the evidence and proposed measurable next test in `tool-review.md`,
record your decision in the PR, make any accepted improvement separately, then rerun
the tests and collector. Existing `shared/ai_loop.py` and other pipeline scopes are
unchanged. A model cannot decide whether a plant is diseased or a PR is mergeable.

## Lab 7 and merge sequence

After reading the signed-in Lab 7 and its linked reference, this adapts its enterprise
integration lessons to gardening rather than copying the enrolment demo:

| Lab lesson | Almanac application |
| --- | --- |
| Explicit tool selection and opt-in UI | Three named, read-only tools; checkbox plus server-side off switch; real MCP calls at `/tools/run`. |
| Purpose, schema, failure and responsibility boundaries | Typed input/output discovery, bounded catalogue API, visible errors, estimate labels, and no diagnosis/mutation tools. |
| Execute before interpreting | `mcp_evidence.py` stores actual inputs/outputs and timestamps, never a guessed execution. |
| Plan → Act → Observe → Adapt | Choose sample queries → execute → capture/review → one bounded revision; human approves any subsequent change. |
| Separate backend, UI and automated validation | HTTP/API tests, real stdio/HTTP protocol tests, browser explorer and deterministic pipeline tests. |
| Independent local review and evidence reports | Qwen proposer, Llama reviewer, strict JSON, four reports plus raw evidence, separate human decision. |

The lab's student-count/project-files/CI tools are intentionally not exposed to
gardening users. No arbitrary filesystem access, shell execution or CI-policy claims
were added. This is a domain adaptation, not a claim of completing lab assessment.

- [UTS Lab 7: MCP and Enterprise Integrations](https://canvas.uts.edu.au/courses/39716/pages/lab-7-mcp-and-enterprise-integrations?module_item_id=2579498)
- [Lab's linked implementation reference](https://github.com/Georges034302/asd-labs/blob/main/Lab_07_MCP_and_Enterprise_Integrations.md)
- [Official Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [MCP specification](https://modelcontextprotocol.io/specification/latest)

The branch is stacked on #35 and contains all of #34 and #35. Review the MCP diff
against #35. Merge order is #34 → #35 → this PR. Main requires an approving review.
After each parent merge, retarget the child to main and verify its diff and checks.
Squash/rebase merges change commit identities: if GitHub shows the parent's commits
again, replay only the child's commits onto the new main, preserving a backup branch.
Do not merge a child back into an already merged parent branch.

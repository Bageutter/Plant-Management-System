# Cloud AI evidence (bonus B1–B4)

These files come from the opt-in bonus profile: `gh workflow run cloud-deployment.yml -f profile=bonus`. It deploys four internal-only container apps next to the baseline:

- `plantms-prod-ollama` runs Ollama with `qwen3:4b-instruct` and `qwen2.5vl:3b` on 4 vCPU / 8 GiB, with the models on Azure Files.
- `plantms-prod-mcp` is the MCP server.
- `plantms-prod-rag` is the RAG server.
- `plantms-prod-agents` is the Multi-Agent Server.

Each feature reaches them through its own backend: browser → proxy → feature backend → AI app.

| File | What |
| --- | --- |
| `latest.md` / `latest.json` | deployment report of the bonus run ([39745279626](https://github.com/Bageutter/Plant-Management-System/actions/runs/39745279626), commit `7dbd213`). The smoke test passed and AI is enabled. |
| `ai-e2e.txt` | **the passing check**: `scripts/deploy/azure-ai-e2e.py` against the live public URL, B1–B4 through the same routes the UI calls |
| `ai-e2e-deploy-run.txt` | the check as it ran inside that deploy job: 3/7. Ollama was still downloading its ~6 GB of models on its first start, and the script then waited for the connection to close rather than for the stream's final event. Both are fixed: the check now waits for the models and reads the stream event by event, and the workflow step now fails when the check fails (`pipefail`). |

`ai-e2e.txt` steps:

- **B1 AI-Mode:**
  - A Plant Health assessment streamed through the agentic loop (vision model + reviewer).
  - An Almanac chat answer.
- **B2 MCP:** `list_health_assessments` through the cloud MCP server.
- **B3 RAG:** the index is rebuilt from the features, then a grounded answer with citations is given.
- **B4 Multi-Agent:** Planner → Worker → Reviewer → human review (partial acceptance) on the same plant.

Cost: about US$0.5 per hour while the AI apps are warm. Running `gh workflow run cloud-deployment.yml` (the baseline) scales them back to zero.

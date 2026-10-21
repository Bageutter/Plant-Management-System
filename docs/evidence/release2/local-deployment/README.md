# Local deployment evidence (21 Oct 2026)

The integrated Release 2 application running locally on an 8 GB M1 MacBook:
six containers from `docker-compose.yml` (proxy, frontend, auth, vgarden,
almanac, health), with AI-Mode (Ollama), the MCP Server, the RAG Server and the
Multi-Agent Server as separate non-containerised processes on the host.

| File | What it shows |
|---|---|
| [`check.txt`](check.txt) | `scripts/test/local-deployment-check.sh`: all 31 checks pass. Containers running, no AI service in compose, each host service healthy, the UI and every backend reachable through the proxy, and each backend reaching the host services from inside its container. |
| [`mcp-server.txt`](mcp-server.txt), [`rag-server.txt`](rag-server.txt), [`multi-agent-server.txt`](multi-agent-server.txt) | Start-up and request logs of each host service, one process each. |
| [`compose-logs.txt`](compose-logs.txt) | The last 40 lines of each container's log. |

Reproduce (one terminal per service):

```sh
ollama serve                                         # AI-Mode, :11434
python ai-services/mcp-server/server.py              # :5105
python ai-services/rag-server/app.py                 # :5106
cd ai-services/multi-agent-server && python app.py   # :8003
docker compose up -d --build                         # containers, :3000
bash scripts/test/local-deployment-check.sh | tee docs/evidence/release2/local-deployment/check.txt
```

The RAG index starts empty (`"chunks": 0` in `check.txt`) on a fresh database; sync
each feature's source from its integrations page before using RAG questions.

A second run on Windows/WSL (Guhan Sundar), with one terminal per service and a full
Plant Health walkthrough — AI-Mode assessments, an MCP tool, a RAG answer, and the
Planner → Worker → Reviewer → Human Review workflow through the health backend from the
terminal and from the records page — is in
[`health-guhan/`](health-guhan/README.md).

# Release 2 design flow

Diagrams for the technical report. They render on GitHub, or paste a block into
<https://mermaid.live> to export a PNG. The cloud deployment and CI/CD architecture
is in [`docs/deployment/azure.md`](../../deployment/azure.md) §1.

## 1. Application design flow

The required flow: Frontend UI → Backend/API → Database, the Release 1 AI-Mode,
MCP and RAG flows, and the Release 2 Multi-Agent flow.

```mermaid
flowchart LR
    UI["Frontend UI<br/>(Jinja + HTMX + Alpine,<br/>through the nginx proxy :3000)"]

    subgraph Backends["Backend/API (Flask containers)"]
        AU[auth]
        VG[vgarden]
        AL[almanac]
        HE[health]
    end

    DB[("Database<br/>SQLite per service locally,<br/>PostgreSQL in Azure")]

    subgraph Host["Non-containerised local AI services"]
        AIM["AI-Mode<br/>Ollama :11434"]
        MCP["MCP Server :5105<br/>controlled tools"]
        RAG["RAG Server :5106<br/>retrieval + cited answers"]
        subgraph MAS["Multi-Agent Server :8003"]
            PL[Planner] --> WO[Worker] --> RE[Reviewer]
        end
    end

    HR{{"Human Review<br/>accept / partially accept /<br/>request changes / reject"}}

    UI --> Backends --> DB
    Backends -- "1 AI-Mode: grounded chat / assessment" --> AIM
    Backends -- "2 MCP: tool call" --> MCP
    Backends -- "3 RAG: question" --> RAG
    VG -- "4 Multi-Agent: task + this garden's records" --> PL
    RE --> HR
    HR -- "request changes (feedback)" --> PL
    HR -- "decision" --> VG
    MCP & RAG & PL & WO & RE --> AIM
    Backends -- "response" --> UI
```

| Flow | Path | Code |
|---|---|---|
| CRUD | UI → backend → database | each service's `routes.py`, Flask-Migrate |
| 1. AI-Mode | UI → backend → Ollama (Plan → Act → Observe → Adapt) → UI | `shared/ai_loop.py`, `*/ai.py` |
| 2. MCP | UI → backend → MCP Server → the owning service's API → UI | `ai-services/mcp-server/` |
| 3. RAG | UI → backend → RAG Server → retrieval + Ollama → cited answer → UI | `ai-services/rag-server/` |
| 4. Multi-Agent | UI → vgarden → Multi-Agent Server → Planner → Worker → Reviewer → Human Review on the garden page → response | `vgarden/garden_workflows.py`, `ai-services/multi-agent-server/` ([evidence](multi-agent-vgarden.md)) |

## 2. Multi-Agent workflow states

```mermaid
stateDiagram-v2
    [*] --> received: POST /workflow (task, source, evidence)
    received --> planning: POST /workflow/run
    planning --> working: Planner saved a plan
    working --> reviewing: Worker answered from the evidence
    reviewing --> awaiting_human_review: Reviewer verdict + issues
    awaiting_human_review --> accepted: accept (reason required if the Reviewer said revise)
    awaiting_human_review --> partially_accepted: partially accept (feedback required)
    awaiting_human_review --> rejected: reject
    awaiting_human_review --> changes_requested: request changes (feedback)
    changes_requested --> planning: revised run, feedback goes to Planner and Worker
    planning --> failed
    working --> failed
    reviewing --> failed
    failed --> planning: retry
    accepted --> [*]
    partially_accepted --> [*]
    rejected --> [*]
```

Every transition is an event in the server's SQLite store, exported by `audit.py` as
[`workflow_history.jsonl`](workflow_history.jsonl) and
[`coordination_audit.jsonl`](coordination_audit.jsonl).

## 3. Local deployment

```mermaid
flowchart TB
    B[Browser] -- "http://localhost:3000" --> P

    subgraph Compose["docker compose (containers)"]
        P[proxy nginx :3000] --> F[frontend] & A[auth] & V[vgarden] & AL[almanac] & H[health]
        V & A & AL & H --- VOL[("SQLite files<br/>in volumes / instance")]
    end

    subgraph HostSvc["Host terminals (non-containerised)"]
        T1["terminal 1: ollama serve :11434"]
        T2["terminal 2: mcp-server/server.py :5105"]
        T3["terminal 3: rag-server/app.py :5106"]
        T4["terminal 4: multi-agent-server/app.py :8003"]
        T5["terminal 5: tools/ai-loop/validate.py<br/>(agentic-loop review modes)"]
    end

    V & AL & H -- "host.docker.internal" --> T1 & T2 & T3
    V -- "host.docker.internal" --> T4
```

Checked by [`scripts/test/local-deployment-check.sh`](../../../scripts/test/local-deployment-check.sh);
the saved run is [`local-deployment/`](local-deployment/).

## 4. Testing and release evidence pipeline

```mermaid
flowchart LR
    C["git commit"] --> PC["pre-commit hooks<br/>Ruff S · detect-secrets ·<br/>pip-audit · pytest"]
    PC -- "pass" --> PU["git push"]
    PC -- "fail" --> X1["commit blocked"]
    PU --> CI["GitHub Actions per feature<br/>lint · endpoint tests · build ·<br/>compose smoke (AI disabled)"]
    CI -- "main, all green" --> CD["cloud-deployment.yml<br/>Bicep · ACR · Container Apps ·<br/>cloud smoke · report"]
    PC -. ".security-reports/" .-> TR["agentic loop<br/>Testing Review"]
    CI -. "runs, jobs, JUnit" .-> TR
    CD -. "latest.json + live probes" .-> CR["agentic loop<br/>Cloud Deployment Review"]
    TR --> HD{{"human decision"}}
    CR --> HD2{{"human release decision<br/>release / hold / rollback"}}
```

| Stage | Evidence |
|---|---|
| Pre-commit | [`pre-commit-yunus.md`](pre-commit-yunus.md) (`scripts/security/report.py`) |
| Post-commit CI | GitHub Actions runs and the `*-test-evidence-*` artifacts |
| Agentic-loop reviews | `review-*.json` here, logs in `tools/ai-loop/logs/reports/review-*/` |
| Cloud deployment | `cloud-deployment/latest.md` / `latest.json` (from `scripts/deploy/azure-report.sh`) |

# AI architecture

## Local-first inference — the non-negotiable

Every model call in the project goes to a **locally hosted [Ollama](https://ollama.com)
instance**. No prompt, photo, garden snapshot, or plant record is ever sent to a
third-party API. This is a hard constraint, not a default:

- `health/` states it in the service README and in `health/ai.py`'s module
  docstring: *"images and descriptions are sent to an Ollama instance on the
  local network and never to a third party."*
- `almanac/ai.py` and `vgarden/ai.py` both open with *"all inference stays on a
  locally hosted Ollama instance."*
- The only outbound internet call anywhere near the AI path is `vgarden/weather.py`
  hitting Open-Meteo for coordinates and a forecast — public data, no API key,
  no user content in the request.

## Topology

```mermaid
flowchart LR
    subgraph Browser
        U[User]
    end

    subgraph "compose network (containers)"
        P[nginx proxy :3000]
        A[almanac :5000]
        V[vgarden :5000]
        H[health :5000]
        AU[auth :5000]
        F[frontend :5000]
    end

    subgraph "host (non-containerised, local only)"
        O[("AI-Mode: Ollama :11434")]
        MCP["MCP server :5105"]
        RAG["RAG server :5106"]
        MAS["Multi-Agent Server :8003<br/>Planner / Worker / Reviewer"]
    end

    OM[["Open-Meteo\n(public, no key)"]]

    U --> P
    P --> F & AU & A & V & H
    A & V & H -- "host.docker.internal" --> O
    A & V & H -. "MCP tools" .-> MCP
    A & V & H -. "grounded Q&A" .-> RAG
    V -. "garden workflows" .-> MAS
    MCP & RAG & MAS --> O
    V -- "coords + forecast" --> OM
    A -. "cookie -> /me" .-> AU
```

AI-Mode, MCP, RAG and the Multi-Agent Server run on the host, outside Docker, as
the brief requires; none of them is a compose service. The containers reach them
through `host.docker.internal` (`extra_hosts: host-gateway` makes that work on
Linux engines too). Each URL is an env var with a host default:

| Service | Env var in compose | Default |
|---|---|---|
| Ollama (almanac / vgarden / health) | `ALMANAC_OLLAMA_URL` / `VGARDEN_OLLAMA_URL` / `HEALTH_OLLAMA_URL` → `OLLAMA_URL` | `http://host.docker.internal:11434` |
| MCP | `MCP_SERVER_URL` | `http://host.docker.internal:5105/mcp` |
| RAG | `RAG_SERVER_URL` | `http://host.docker.internal:5106` |
| Multi-Agent (vgarden) | `MULTI_AGENT_URL` | `http://host.docker.internal:8003` |

Each integration has an on/off switch (`AI_MODE_ENABLED`, `MCP_ENABLED`,
`RAG_ENABLED`, `MULTI_AGENT_ENABLED`). CI and the cloud baseline turn all of them
off, so the app runs without any model.

### GPU

The host's Ollama uses the GPU by itself (Metal on Apple silicon, CUDA on NVIDIA),
so no compose override is needed.

## Model matrix

| Model | Used by | Role | Why this model |
|---|---|---|---|
| `qwen3:4b-instruct` | almanac, vgarden (ACT); `tools/ai-dev` (proposer) | Draft the answer / proposal from the grounding | Instruction-tuned, reads JSON grounding carefully, approves well-grounded drafts on the first reviewer pass, small enough for CPU dev |
| `llama3.1:8b` | almanac, vgarden (OBSERVE); `tools/ai-dev` (reviewer) | Independently review the draft against the same grounding | A *different* family from the proposer (independence), noticeably stricter — good for catching unsupported claims |
| `qwen2.5vl:3b` | health | Vision + text plant-health assessment | Fastest vision model that still returned valid structured output in every test case (see `health/README.md` perf table); `moondream` was smaller but failed text-only JSON |

Configuration knobs (per service, via env — see each service README and
[`context-management.md`](context-management.md) for the budgets):

| Env var | Meaning |
|---|---|
| `OLLAMA_URL` | Ollama endpoint (`http://host.docker.internal:11434` in compose) |
| `OLLAMA_MODEL` | Proposer / assessment model |
| `OLLAMA_REVIEW_MODEL` | Reviewer model (almanac, vgarden); empty ⇒ single-shot |
| `OLLAMA_AUTO_PULL` | Pull the model on first use if missing |
| `OLLAMA_KEEP_ALIVE` | How long a model stays resident (health; `30m`) |
| `OLLAMA_TIMEOUT` / `OLLAMA_PULL_TIMEOUT` | Request / pull timeouts |
| `AI_LOOP_MAX_ITERATIONS` | Max ACT/OBSERVE rounds (default 2) |
| `AI_LOOP_LOG_DIR` | Where JSONL + transcripts are written |

## Where AI sits in the domain

The project's rule is **"the Virtual Garden stores what is happening; other
services determine what it means."** AI lives on the *interpretation* side and
the *input* side, never inside the Virtual Garden's representation:

```mermaid
flowchart TD
    subgraph Input["AI input layer (mostly future)"]
        NL[Natural language] --> EX[AI extraction]
        IMG[Photos] --> EX
    end
    EX -->|structured observations| VG[Virtual Garden Service\nrepresentation only]

    VG -->|garden snapshot| VGA[vgarden chat\nP -> A -> O -> A]
    W[Open-Meteo] -->|weather| VGA

    ALM[(Plant references)] -->|selected records| ALMA[almanac chat\nP -> A -> O -> A]

    PHOTO[Photo / description] --> HLTH[health assessment\nPerceive→Reason→Act→Observe→Repeat]
```

## Not built yet

These directories are committed as placeholders (`.keep` files) and represent the
intended expansion. Nothing in them runs today; the architecture doc in the root
README describes the target shape.

| Path | Intended role |
|---|---|
| `ai-services/mcp-server/` | **Built (Release 1):** the shared local MCP server. Plant Health, Plant Almanac and Virtual Garden tools are all implemented. See [`mcp-rag-design.md`](mcp-rag-design.md). |
| `ai-services/rag-server/` | **Built (Release 1):** the shared local RAG server. `health`, `almanac` and `vgarden` sources are all implemented. |
| `ai-services/multi-agent-server/` | **Built (Release 2):** the shared local Multi-Agent Server (Planner → Worker → Reviewer → Human Review). Plant Almanac, Virtual Garden and Plant Health all start workflows through their own backends; see its [README](../../ai-services/multi-agent-server/README.md). |
| `ai-services/ai-mode/` | A conversational "manage my garden" front door spanning vgarden + almanac + health |
| `ai-input/` | Convert unstructured natural-language / image input into structured Virtual Garden updates |

When any of these is implemented, add a row to the service map in
[`README.md`](README.md) and a grounding section to
[`context-management.md`](context-management.md).

# Plant Management System

A smart plant management platform designed for **small home gardens**.

The system maintains a digital representation of a user's garden and combines information from manual input, environmental data, AI-assisted observations, and plant knowledge services to help users understand and manage their plants.

The project is built around a **microservice architecture**, with the **Virtual Garden Service** acting as the source of truth for the current state of a garden.

## github workflow / how we work 💪

branch → PR → review → merge.

each contributor has a personal workflow placeholder (`amy.yml`, `yunus.yml`, `guhan.yml`) — implement yours as needed.

shared CI:
- [`ruff.yml`](.github/workflows/ruff.yml) — lints every Python service on every PR and push to `main`
- [`integration-ci.yml`](.github/workflows/integration-ci.yml) — builds the stack, smoke-checks the endpoints, and tears it all down

before merging: CI is green, at least one review, no unresolved comments.

## for devs 🤓☝️ (amy,guhan,yunz)

all docker commands from the root (important!!)

### 1. start docker

open Docker Desktop, then check it's alive:

```bash
docker version
docker ps
```

> **Showcasing / demoing?** Follow **[DEMO.md](DEMO.md)** — it covers the clean
> start (`docker compose down -v` first), pulling + pre-warming the models, the
> demo login, and what each feature shows.

### 2. start stuff

everything:

```bash
docker compose up -d --build
```

orrrr just what you need (the `proxy` is what publishes port 3000, so include it):

```bash
docker compose up -d --build proxy auth vgarden
docker compose up -d --build proxy auth ollama almanac
```

Everything is served through the nginx proxy on **one port, 3000**, and path-routed:

| service | url |
| --- | --- |
| frontend | http://localhost:3000/ |
| auth | http://localhost:3000/auth/account |
| vgarden | http://localhost:3000/vgarden/ |
| almanac | http://localhost:3000/almanac/ |
| almanac api | http://localhost:3000/almanac/api/plants |
| plant health | http://localhost:3000/health/plant-health-records/ |

### 3. logs, troubleshoot, stop

```bash
docker compose ps               # what's running
docker compose logs -f          # all logs
docker compose logs -f almanac  # one service
docker compose down             # stop (keeps data)
```

## Agentic AI workflow

The almanac and virtual-garden chat answers run through an explicit
**Plan → Act → Observe → Adapt** loop (a second model reviews each draft; the loop
revises until approved). Every phase is logged for evidence — stdout, JSONL, and a
per-run transcript. See **[docs/agentic-ai-workflow.md](docs/agentic-ai-workflow.md)**
and `python tools/ai-loop/view.py`.

## Overview

Users can describe and update their garden through several input methods:

* **Natural language**

  * "I planted two tomato seedlings today."
  * "The basil leaves are starting to turn yellow."
* **Photos**

  * Images of plants, leaves, pests, soil, etc.
* **Traditional forms**

  * Planting dates
  * Watering
  * Fertilising
  * Pruning
  * Harvesting
* **Automatically collected data**

  * Weather
  * Climate
  * Geospatial information
  * Other environmental data

AI can be used to convert less structured inputs such as text and images into structured garden observations.

These observations ultimately update the user's **Virtual Garden**.

---

## Architecture

```mermaid
flowchart LR
    User[User]

    Weather[Automated Environmental Data<br/>Weather / Climate / Geospatial]
    AI[AI-assisted Input<br/>Natural Language / Images]
    Forms[Traditional Forms]

    VG[Virtual Garden Service]

    Almanac[Plant Almanac Service<br/>MCP / RAG]
    Health[Plant Health Monitoring Service]

    Scheduler[Scheduler]
    Notify[Notification Service]

    User --> Weather
    User --> AI
    User --> Forms

    Weather -->|Garden observations| VG
    AI -->|Structured garden observations| VG
    Forms -->|Garden updates| VG

    Almanac -->|Plant reference data| VG

    VG -->|Garden state| Health
    Almanac -->|Plant knowledge| Health

    VG -->|Relevant changes| Scheduler
    Scheduler --> Notify
    Notify --> User
```

---

## Core Services

### Virtual Garden Service

The **Virtual Garden Service** maintains the current representation of a user's physical garden.

Examples of information it may store include:

* Gardens
* Garden beds
* Plants
* Plant locations
* Species/variety references
* Planting dates
* Growth stages
* Watering events
* Fertilisation events
* Pruning events
* Harvest events
* User observations
* Environmental observations
* Plant state/history

The service should be concerned with **representation, not interpretation**.

For example:

> "The tomato plant has three yellow leaves."

is valid garden state.

Determining:

> "The tomato plant probably has a nitrogen deficiency."

belongs to the **Plant Health Monitoring Service**.

### Virtual Garden Design Principles

The Virtual Garden Service should:

* Maintain the authoritative representation of the garden.
* Accept structured updates from different input methods.
* Keep historical garden events where appropriate.
* Validate references against other services when required.
* Expose garden state to other services.
* Publish relevant changes for downstream systems.

It should **not**:

* Diagnose plant diseases.
* Determine whether a plant is healthy.
* Generate gardening advice.
* Perform complex plant knowledge retrieval.
* Duplicate information owned by another service.
* Maintain a global database containing every piece of system data.

When information belongs to another domain, the Virtual Garden Service should query the service responsible for it.

---

## Plant Almanac Service

The **Plant Almanac Service** provides general knowledge about plants.

### Current implementation

The current service provides public plant reference pages and APIs plus an authenticated,
Ollama-powered chat at <http://localhost:3000/almanac/>.

See [the Plant Almanac microservice README](almanac/README.md) for setup, architecture,
endpoints, configuration, tests, and persistence.

### Intended knowledge scope

Examples include:

* Plant species
* Cultivars
* Expected growth characteristics
* Preferred soil
* Sunlight requirements
* Water requirements
* Temperature tolerances
* Seasonal information
* Companion planting information
* Common diseases
* Common pests
* Gardening recommendations

The service may use:

* Structured plant databases
* Retrieval-Augmented Generation (**RAG**)
* Large language models
* External horticultural datasets

Other services should query the Almanac rather than maintaining their own copies of this information.

The service should also be queryable through **MCP**, allowing AI assistants to access plant knowledge directly.

---

## Plant Health Monitoring Service

The **Plant Health Monitoring Service** analyses the current state of the garden.

It combines:

1. The user's actual garden state from the **Virtual Garden Service**
2. Expected plant characteristics from the **Plant Almanac Service**

For example:

```text
Virtual Garden

Tomato Plant
- planted 6 weeks ago
- leaves becoming yellow
- watered every day
- soil currently very wet

        +

Plant Almanac

Tomato
- prefers well-draining soil
- excessive watering may cause root problems

        ↓

Plant Health Monitoring

Potential overwatering detected.
```

The health service can perform tasks such as:

* Detecting abnormal plant conditions
* Identifying possible diseases
* Detecting pest symptoms
* Recognising watering problems
* Comparing growth against expected growth stages
* Identifying environmental stress
* Producing health scores
* Generating recommendations

This separation keeps health interpretation outside of the Virtual Garden domain.

---

## Scheduler

Garden changes can create or modify future tasks.

For example, adding:

```text
Planted tomato seedlings today.
```

may generate:

```text
Water seedlings
Check seedling establishment
Fertilise
Inspect growth
Expected harvest period
```

If the Virtual Garden changes, relevant scheduled tasks can be recalculated.

```mermaid
sequenceDiagram
    participant User
    participant VG as Virtual Garden
    participant Scheduler
    participant Notification

    User->>VG: Plant tomato seedling
    VG->>Scheduler: Garden updated
    Scheduler->>Scheduler: Generate relevant tasks

    Scheduler->>Notification: Watering reminder
    Notification->>User: Water tomato plant
```

---

## Notifications

The notification system delivers time-sensitive garden information to users.

Possible notifications include:

* Watering reminders
* Fertilising reminders
* Pruning reminders
* Plant health warnings
* Pest alerts
* Frost warnings
* Heat warnings
* Harvest reminders
* Seasonal gardening tasks

Notifications should generally be produced from events generated by other services rather than implementing gardening logic themselves.

---

## Data Input Pipeline

Different forms of user input should ultimately result in a common structured representation.

```mermaid
flowchart TD
    A[User Input]

    A --> B[Natural Language]
    A --> C[Photo]
    A --> D[Form]
    A --> E[Automated Data]

    B --> F[AI Extraction]
    C --> F
    D --> G[Structured Input]
    E --> G

    F --> H[Structured Garden Update]
    G --> H

    H --> I[Virtual Garden Service]
```

For example:

```text
User:
"I planted three basil plants in the herb bed yesterday."
```

could become:

```json
{
  "action": "plant",
  "plant": {
    "species": "basil",
    "quantity": 3
  },
  "location": "herb-bed",
  "planted_at": "2026-08-20"
}
```

The Virtual Garden Service then validates and records the update.

---

## Event-Driven Communication

Where appropriate, changes to the Virtual Garden should produce domain events.

For example:

```text
plant.created
plant.updated
plant.removed

watering.recorded
fertilising.recorded
observation.created

garden.updated
```

Other services can subscribe to these events without tightly coupling themselves to the Virtual Garden implementation.

```mermaid
flowchart LR
    VG[Virtual Garden]

    VG -->|plant.updated| Bus[Event Bus]

    Bus --> Health[Health Monitoring]
    Bus --> Scheduler[Scheduler]
    Bus --> Analytics[Analytics]
```

For operations requiring an immediate response, services can communicate synchronously through APIs or MCP.

---

## Example User Flow

A user notices unusual leaves on their tomato plant.

### 1. User submits a photo

```text
"This tomato plant looks weird."
```

### 2. AI processes the input

The AI extracts observations such as:

```text
Plant: Tomato #3
Observation:
- several lower leaves are yellow
- leaf edges appear brown
```

### 3. Virtual Garden is updated

The Virtual Garden records the observation without diagnosing it.

### 4. Health Monitoring receives the change

It retrieves:

```text
Virtual Garden:
- current plant state
- watering history
- environmental conditions
```

and combines it with:

```text
Plant Almanac:
- tomato disease information
- nutrient requirements
- environmental tolerances
```

### 5. Health Monitoring produces an assessment

For example:

```text
Possible overwatering.

Confidence: 72%

The plant has been watered frequently and the soil has
remained wet for several days.
```

### 6. User receives a notification

The application can surface the warning and recommended actions.

---

## Service Boundaries

| Service                  | Responsibility                                          |
| ------------------------ | ------------------------------------------------------- |
| **Virtual Garden**       | Represent the user's real garden                        |
| **Plant Almanac**        | Provide general plant knowledge                         |
| **Health Monitoring**    | Interpret garden state and detect problems              |
| **Scheduler**            | Maintain future garden tasks                            |
| **Notification Service** | Deliver alerts and reminders                            |
| **AI Input Layer**       | Convert unstructured input into structured observations |

A useful rule is:

> **The Virtual Garden stores what is happening. Other services determine what it means.**

---

## AI Integration

AI is intended to complement the system rather than replace clear service boundaries.

Potential AI use cases include:

* Natural-language garden updates
* Image understanding
* Plant identification
* Observation extraction
* Conversational garden management
* Plant health reasoning
* RAG over gardening literature
* Recommendation generation

For example, a user should eventually be able to say:

```text
How are my tomatoes doing?
```

An AI assistant could query:

```text
Virtual Garden
    ↓
current tomato plants

Health Monitoring
    ↓
current health assessments

Plant Almanac
    ↓
relevant tomato knowledge
```

and combine the responses into a useful answer.

Services should therefore expose queryable interfaces, with **MCP** being particularly useful for AI-assisted interactions.

---

## Project Goals

The system is primarily intended for **small gardens**, including:

* Backyard gardens
* Courtyard gardens
* Balcony gardens
* Raised garden beds
* Community garden plots
* Small greenhouse setups

The goal is not to build an enterprise farm management platform.

Instead, the project aims to make managing a small garden easier by creating a continuously updated digital model of the garden that other intelligent services can reason over.

---

## Initial MVP

A reasonable first version of the system could support:

* Creating a garden
* Creating garden beds/areas
* Adding plants
* Recording plant locations
* Recording watering
* Recording fertilising
* Recording observations
* Natural-language updates
* Basic image observations
* Plant Almanac lookup
* Basic plant health assessments
* Scheduled watering reminders
* Notifications
* Garden history

More sophisticated features can then be added without expanding the responsibilities of the core Virtual Garden Service.

---

## Long-Term Vision

The system should eventually allow a user to manage their garden conversationally.

For example:

```text
User:
I planted three tomato seedlings in the north bed.

Assistant:
Added three tomato seedlings to the north bed.
```

Later:

```text
User:
Do I need to do anything in the garden today?

Assistant:
Your basil is due for watering.

Your tomato plants look healthy, although the expected
temperature tomorrow is unusually high. Consider watering
them early in the morning.
```

The underlying system remains modular:

```text
                ┌──────────────────────┐
                │    AI Assistant      │
                └──────────┬───────────┘
                           │ MCP / APIs
          ┌────────────────┼────────────────┐
          │                │                │
          ▼                ▼                ▼
    Virtual Garden   Plant Almanac   Health Monitoring
          │
          ▼
      Scheduler
          │
          ▼
    Notifications
```

This keeps the architecture extensible while ensuring that each service has a clear and maintainable responsibility.

---

## Running the Frontend Locally

The pages under `shared/frontend/templates/` are Jinja templates (e.g. `index.html` starts with `{% extends "base.html" %}`), so opening them directly as local files won't work — they need to be rendered by Flask.

From `shared/frontend/`:

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Run this way, the standalone frontend is on **http://127.0.0.1:5000**.

Or, with Docker, from the repository root (brings up every service behind the proxy):

```bash
docker compose up --build
```

Then open **http://127.0.0.1:3000** in your browser.

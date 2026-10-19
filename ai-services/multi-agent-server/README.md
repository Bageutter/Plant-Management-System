# Multi-Agent Server

- `planner.py` — decides the steps.
- `worker.py` — follows the plan using plant evidence.
- `reviewer.py` — checks the result.
- `human_review.py` — records the user’s decision.
- `application_integration.py` — connects feature backends to this server.

```mermaid
flowchart TD
    App[Application] --> Server[Multi-Agent Server]
    Server --> Planner[Planner]
    Planner --> Worker[Worker]
    Worker --> Reviewer[Reviewer]
    Reviewer --> Human[Human review]
    Human -->|Approve| Result[Return result to application]
    Human -->|Correct| Planner
    Human -->|Reject| Stop[Stop workflow]
```

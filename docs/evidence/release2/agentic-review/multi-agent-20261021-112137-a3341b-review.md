# Multi-Agent Workflow Review — validation log

Produced by `python tools/ai-loop/evidence_review.py --mode multi-agent` (shared agentic loop,
Plan → Act → Observe → Adapt, local Ollama only). This log is advisory: it supports the
team's confirmation of the Multi-Agent workflow evidence and does not replace it.

| | |
|---|---|
| Evidence reviewed | live Multi-Agent Server at `http://127.0.0.1:8003` (fetched 2026-10-21T11:21:37+00:00) |
| Workflows / runs | 2 / 3 (final states: {'partially_accepted': 1, 'accepted': 1}) |
| Reviewer recommendations / human decisions | {'revise': 3} / {'request_changes': 1, 'partially_accept': 1, 'accept': 1} |
| Loop run | `multi-agent-20261021-112137-a3341b` — 2 iteration(s), iteration cap reached without reviewer approval; read the OBSERVE issues below |
| Proposer / reviewer | `gemma3:4b` / `qwen2.5vl:3b` at `http://localhost:11434` |
| Transcript | `tools/ai-loop/logs/reports/multi-agent/multi-agent-20261021-112137-a3341b.md` |
| Reviewed at | 2026-10-21T11:21:52+00:00 |

## Decision

| Decision | Workflows reviewed | Findings (high / medium / low) | Code checks |
|---|---|---|---|
| **pass** | 2 | 0 / 0 / 0 | 0 violation(s) computed in code |

**Summary:** 1 finding(s) in the model's draft were not confirmed by the code checks and were removed (see the corrections); read its prose with that in mind. Two workflows were reviewed for the 'health' source, resulting in one partially accepted and one accepted run. The worker consistently cited the same evidence chunks, and the reviewer recommended revisions in both cases.

Decision meanings: `pass` = every required check holds (low findings, if any, are informational); `pass_with_findings` = the evidence stands but the medium findings should be addressed before the report is finalised; `fail` = at least one high finding, the evidence does not show what it must; `insufficient_evidence` = nothing reviewable was found, regenerate the evidence. Only a check computed in code can be high or medium.

## Findings

_No findings._

## Implementation and review recommendations

1. Ensure all 'revise' recommendations are followed by a human decision with a recorded reason in 'human_feedback'.
2. Verify that 'cited_chunk_ids' accurately reflect the cited evidence chunks.
3. Monitor the frequency of 'revise' recommendations to identify potential issues in the initial planning or worker stages.
4. Review the 'reviewer_issues' to understand the types of problems the reviewer is identifying.

## Workflows reviewed

| Workflow | Source | Runs | Final state | Reviewer per run | Human decision per run | Task |
|---|---|---|---|---|---|---|
| `a7f23d6d` | health | 2 | partially_accepted | revise, revise | request_changes (reason), partially_accept (reason) | Summarise how the health of this plant has changed across its assessments and which issues keep recurring. |
| `ae71c81a` | health | 1 | accepted | revise | accept (reason) | Which issues were recorded for this plant, and did its health score change between assessments? |

Required pipeline per run: planning (Planner) → working (Worker) → reviewing (Reviewer) →
awaiting_human_review → human decision. Metrics cross-checked: tracked workflows
2, hand-off success 1.00, completion
1.00, human approval 1.00, rework ratio
0.3333333333333333, generated 2026-10-21T11:21:37.183746+00:00.

## Checks computed in code

_Every code check held: stage order, human decisions, citations, reasons, audit and metrics._

## Code corrections applied to the final draft

The model's output is untrusted: `normalise()` in `tools/ai-loop/multi_agent_review.py`
re-validates it against the grounding and the review rules. Changes it made:

- dropped finding 'The Worker cited chunk ids ['health-history', 'health-3', 'health-2', 'health-1'': the worker_citations check holds for a7f23d6d-9f83-41bd-bb01-02402e50244a in the grounding, so nothing confirms it

## Loop trace

| Phase | Iteration | Outcome | +ms |
|---|---|---|---|
| PLAN |  | source=server workflows=2 runs=3 human_decisions=3 reviewer_revise=3 code_findings=high=0 medium=0 low=0 evidence_gaps=0 | 0 |
| ACT | 1 | draft of 819 chars; feedback: (none) | 8979 |
| OBSERVE | 1 | revise; issues: deterministic check: the code had to correct the draft -> dropped finding 'The Worker cited chunk ids ['health-history', 'health-3', 'health-2', 'health-1'': the worker_citations check holds for a7f23d6d-9f83-41bd-bb01-02402e50244a in the grounding, so nothing confirms it; pass_with_findings is inconsistent with the findings -> pass | 8980 |
| ADAPT | 1 | revise; guidance: Return findings that are exactly the grounding.code_checks entries (same check or area, subject and severity, your own wording and recommendation) and a decision that follows them; the grounding confirms nothing else. Corrections made: dropped finding 'The Worker cited chunk ids ['health-history', 'health-3', 'health-2', 'health-1'': the worker_citations check holds for a7f23d6d-9f83-41bd-bb01-02402e50244a in the grounding, so nothing confirms it; pass_with_findings is inconsistent with the findings -> pass | 8980 |
| ACT | 2 | draft of 879 chars; feedback: Return findings that are exactly the grounding.code_checks entries (same check or area, subject and severity, your own wording and recommendation) and a decision that follows them; the grounding confirms nothing else. Corrections made: dropped finding 'The Worker cited chunk ids ['health-history', 'health-3', 'health-2', 'health-1'': the worker_citations check holds for a7f23d6d-9f83-41bd-bb01-02402e50244a in the grounding, so nothing confirms it; pass_with_findings is inconsistent with the findings -> pass | 15319 |
| OBSERVE | 2 | revise; issues: deterministic check: the code had to correct the draft -> dropped finding 'The Worker cited chunk ids ['health-history', 'health-3', 'health-2', 'health-1'': the worker_citations check holds for a7f23d6d-9f83-41bd-bb01-02402e50244a in the grounding, so nothing confirms it | 15321 |
| ADAPT | 2 | stop_capped | 15321 |

## Human confirmation

To be completed by the team after reading this log and the evidence:

- [ ] **Confirmed** — the Multi-Agent workflow evidence stands as reviewed
- [ ] **Confirmed with actions** (list):
- [ ] **Not confirmed** — regenerate the evidence (reason):

Reviewer: ______________________  Date: ____________

# Multi-Agent Workflow Review — validation log

Produced by `python tools/ai-loop/evidence_review.py --mode multi-agent` (shared agentic loop,
Plan → Act → Observe → Adapt, local Ollama only). This log is advisory: it supports the
team's confirmation of the Multi-Agent workflow evidence and does not replace it.

| | |
|---|---|
| Evidence reviewed | `docs/evidence/release2/local-deployment/workflow_history.jsonl`, `docs/evidence/release2/local-deployment/coordination_audit.jsonl`, `docs/evidence/release2/local-deployment/multi-agent-metrics.json` |
| Workflows / runs | 2 / 3 (final states: {'partially_accepted': 1, 'accepted': 1}) |
| Reviewer recommendations / human decisions | {'revise': 3} / {'request_changes': 1, 'partially_accept': 1, 'accept': 1} |
| Loop run | `multi-agent-20261021-112114-0fe60f` — 2 iteration(s), iteration cap reached without reviewer approval; read the OBSERVE issues below |
| Proposer / reviewer | `gemma3:4b` / `qwen2.5vl:3b` at `http://localhost:11434` |
| Transcript | `tools/ai-loop/logs/reports/multi-agent/multi-agent-20261021-112114-0fe60f.md` |
| Reviewed at | 2026-10-21T11:21:36+00:00 |

## Decision

| Decision | Workflows reviewed | Findings (high / medium / low) | Code checks |
|---|---|---|---|
| **pass** | 2 | 0 / 0 / 0 | 0 violation(s) computed in code |

**Summary:** 3 finding(s) in the model's draft were not confirmed by the code checks and were removed (see the corrections); read its prose with that in mind. Corrected in code to pass: no code check supports a different decision. The model's draft said: Two workflows related to plant health assessments were reviewed. One workflow resulted in a partially accepted decision, while the other resulted in an accepted decision. The code checks confirmed that the workflow pipeline was followed and the human decisions aligned with the reviewer's recommendations.

Decision meanings: `pass` = every required check holds (low findings, if any, are informational); `pass_with_findings` = the evidence stands but the medium findings should be addressed before the report is finalised; `fail` = at least one high finding, the evidence does not show what it must; `insufficient_evidence` = nothing reviewable was found, regenerate the evidence. Only a check computed in code can be high or medium.

## Findings

_No findings._

## Implementation and review recommendations

1. The Worker's citations are present in the evidence, as confirmed by the code checks.
2. The human decision aligns with the reviewer's recommendation, as confirmed by the code checks.
3. The workflow pipeline is correctly followed: Planner -> Worker -> Reviewer -> Human Decision.

## Workflows reviewed

| Workflow | Source | Runs | Final state | Reviewer per run | Human decision per run | Task |
|---|---|---|---|---|---|---|
| `a7f23d6d` | health | 2 | partially_accepted | revise, revise | request_changes (reason), partially_accept (reason) | Summarise how the health of this plant has changed across its assessments and which issues keep recurring. |
| `ae71c81a` | health | 1 | accepted | revise | accept (reason) | Which issues were recorded for this plant, and did its health score change between assessments? |

Required pipeline per run: planning (Planner) → working (Worker) → reviewing (Reviewer) →
awaiting_human_review → human decision. Metrics cross-checked: tracked workflows
2, hand-off success 1.00, completion
1.00, human approval 1.00, rework ratio
0.3333333333333333, generated 2026-10-21T10:26:41.584135+00:00.

## Checks computed in code

_Every code check held: stage order, human decisions, citations, reasons, audit and metrics._

## Code corrections applied to the final draft

The model's output is untrusted: `normalise()` in `tools/ai-loop/multi_agent_review.py`
re-validates it against the grounding and the review rules. Changes it made:

- dropped finding 'The Worker cited 'health-history', 'health-3', 'health-2', and 'health-1' as cit': the worker_citations check holds for a7f23d6d-9f83-41bd-bb01-02402e50244a in the grounding, so nothing confirms it
- dropped finding 'The human decision was 'request_changes' despite the reviewer recommending 'revi': the human_decision check holds for a7f23d6d-9f83-41bd-bb01-02402e50244a in the grounding, so nothing confirms it
- dropped finding 'The human decision was 'accept' despite the reviewer recommending 'revise' and c': the human_decision check holds for ae71c81a-e925-4c27-af94-98a445aa6629 in the grounding, so nothing confirms it
- pass_with_findings is inconsistent with the findings -> pass

## Loop trace

| Phase | Iteration | Outcome | +ms |
|---|---|---|---|
| PLAN |  | source=files workflows=2 runs=3 human_decisions=3 reviewer_revise=3 code_findings=high=0 medium=0 low=0 evidence_gaps=0 | 1 |
| ACT | 1 | draft of 1010 chars; feedback: (none) | 13486 |
| OBSERVE | 1 | revise; issues: deterministic check: the code had to correct the draft -> dropped finding 'The Worker cited 'health-history', 'health-3', 'health-2', and 'health-1' as cit': the worker_citations check holds for a7f23d6d-9f83-41bd-bb01-02402e50244a in the grounding, so nothing confirms it; mapped workflow_id '6d25b895-002' (a run id) to its workflow 'a7f23d6d-9f8'; dropped finding 'The human decision was 'request_changes' despite the reviewer recommending 'revi': the human_decision check holds for a7f23d6d-9f83-41bd-bb01-02402e50244a in the grounding, so nothing confirms it; dropped finding 'The human decision was 'accept' despite the reviewer recommending 'revise' and c': the human_decision check holds for ae71c81a-e925-4c27-af94-98a445aa6629 in the grounding, so nothing confirms it; pass_with_findings is inconsistent with the findings -> pass | 13487 |
| ADAPT | 1 | revise; guidance: Return findings that are exactly the grounding.code_checks entries (same check or area, subject and severity, your own wording and recommendation) and a decision that follows them; the grounding confirms nothing else. Corrections made: dropped finding 'The Worker cited 'health-history', 'health-3', 'health-2', and 'health-1' as cit': the worker_citations check holds for a7f23d6d-9f83-41bd-bb01-02402e50244a in the grounding, so nothing confirms it; mapped workflow_id '6d25b895-002' (a run id) to its workflow 'a7f23d6d-9f8'; dropped finding 'The human decision was 'request_changes' despite the reviewer recommending 'revi': the human_decision check holds for a7f23d6d-9f83-41bd-bb01-02402e50244a in the grounding, so nothing confirms it; dropped finding 'The human decision was 'accept' despite the reviewer recommending 'revise' and c': the human_decision check holds for ae71c81a-e925-4c27-af94-98a445aa6629 in the grounding, so nothing confirms it; pass_with_findings is inconsistent with the findings -> pass | 13487 |
| ACT | 2 | draft of 927 chars; feedback: Return findings that are exactly the grounding.code_checks entries (same check or area, subject and severity, your own wording and recommendation) and a decision that follows them; the grounding confirms nothing else. Corrections made: dropped finding 'The Worker cited 'health-history', 'health-3', 'health-2', and 'health-1' as cit': the worker_citations check holds for a7f23d6d-9f83-41bd-bb01-02402e50244a in the grounding, so nothing confirms it; mapped workflow_id '6d25b895-002' (a run id) to its workflow 'a7f23d6d-9f8'; dropped finding 'The human decision was 'request_changes' despite the reviewer recommending 'revi': the human_decision check holds for a7f23d6d-9f83-41bd-bb01-02402e50244a in the grounding, so nothing confirms it; dropped finding 'The human decision was 'accept' despite the reviewer recommending 'revise' and c': the human_decision check holds for ae71c81a-e925-4c27-af94-98a445aa6629 in the grounding, so nothing confirms it; pass_with_findings is inconsistent with the findings -> pass | 22613 |
| OBSERVE | 2 | revise; issues: deterministic check: the code had to correct the draft -> dropped finding 'The Worker cited 'health-history', 'health-3', 'health-2', and 'health-1' as cit': the worker_citations check holds for a7f23d6d-9f83-41bd-bb01-02402e50244a in the grounding, so nothing confirms it; dropped finding 'The human decision was 'request_changes' despite the reviewer recommending 'revi': the human_decision check holds for a7f23d6d-9f83-41bd-bb01-02402e50244a in the grounding, so nothing confirms it; dropped finding 'The human decision was 'accept' despite the reviewer recommending 'revise' and c': the human_decision check holds for ae71c81a-e925-4c27-af94-98a445aa6629 in the grounding, so nothing confirms it; pass_with_findings is inconsistent with the findings -> pass | 22613 |
| ADAPT | 2 | stop_capped | 22614 |

## Human confirmation

To be completed by the team after reading this log and the evidence:

- [ ] **Confirmed** — the Multi-Agent workflow evidence stands as reviewed
- [ ] **Confirmed with actions** (list):
- [ ] **Not confirmed** — regenerate the evidence (reason):

Reviewer: ______________________  Date: ____________

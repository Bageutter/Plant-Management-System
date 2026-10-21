# Contribution log: Yunus Sayed (GitHub `yunz-dev`)

Release 2, Assessment 3. Feature: **Virtual Garden** (`vgarden/`), plus `auth/`,
the nginx proxy, `docker-compose.yml` and the shared agentic loop
(`shared/ai_loop.py`, `tools/ai-loop/`). Every commit below went through the
pre-commit hooks ([`pre-commit-yunus.md`](pre-commit-yunus.md)).

| Date | Commit / PR | Criterion | Work | Evidence |
|---|---|---|---|---|
| 21 Oct | `e62cb1d` → `17c9cc1` on main (#74) | 4 Post-commit CI | `vgarden.yml` tests two named endpoint functions (`routes.create_garden`, `routes.garden_snapshot`), runs on every push to `main`, uploads JUnit, logs and `run.json` for 30 days; image build now waits for lint and tests. 3 files, +223 / −12. | `vgarden/tests/test_endpoints.py`, `vgarden-test-evidence-*` artifacts |
| 21 Oct | `9fb2563` → `0a31150` on main | 1, 2 Multi-Agent | Virtual Garden integration with the shared Multi-Agent Server: an agent-workflow panel on each garden page (start, live stages, plan, Worker answer, Reviewer issues, Accept / Partially accept / Request changes / Reject), owner-scoped routes, `GardenWorkflow` model and migration `0002`. Server side: optional `source` + supplied `evidence` so the server never reads garden data itself, per-source prompts, and a fix so a human's requested changes reach the Worker. 31 files, +1776 / −56; 15 + 6 new tests. | [`multi-agent-vgarden.md`](multi-agent-vgarden.md), `workflow_history.jsonl`, `coordination_audit.jsonl` |
| 21 Oct | `yunz/release2-evidence` | 3 Pre-commit | Fixed all 10 Ruff security findings in `vgarden` and `auth`. `scripts/security/report.py` scans every tracked file of a service through the same hooks and writes a summary that is safe to commit. | [`pre-commit-yunus.md`](pre-commit-yunus.md) |
| 21 Oct | `yunz/release2-evidence` | 8 Agentic-loop review modes | `--mode multi-agent`, `testing` and `cloud-deployment` in `tools/ai-loop/validate.py` (`review.py`): fixed checks, local-model draft, rule + second-model review, bounded revision, human decision, review/validation logs. 19 tests, run in CI. | `review-*.json`, `tools/ai-loop/logs/reports/review-*/` |
| 21 Oct | `yunz/release2-evidence` | Local deployment | AI-Mode moved out of compose: vgarden and health now use the host's Ollama like almanac (the brief keeps AI-Mode non-containerised). `scripts/test/local-deployment-check.sh` checks every container and host service and that each backend reaches them. `auth.yml` now also runs on `main`. | [`local-deployment/`](local-deployment/), [`design-flow.md`](design-flow.md) |
| 21 Oct | `yunz/release2-evidence` | 9 Report | Release 2 design flow, Multi-Agent state, local deployment and evidence pipeline diagrams. | [`design-flow.md`](design-flow.md) |

## Shared with the group

- Cloud deployment (criteria 5–7) is built on `claude/azure-deployment-checkin-74cfaf`.
  The Cloud Deployment Review mode reads that deploy's `latest.json` report and
  checks the deployed commit passed CI first.
- Amy's Multi-Agent Server: the `source`/`evidence` extension and Worker feedback
  fix above were made in her files, with her 19 tests still passing.

## To record before submission

- Release decisions on the three review modes (run them interactively, see
  `tools/ai-loop/README.md`).
- Screenshots listed in `multi-agent-vgarden.md` and the video segment.

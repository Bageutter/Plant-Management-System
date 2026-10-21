# Runtime agentic loop — evidence

Every answer from the **almanac** and **virtual-garden** chat is produced by an
iterating **Plan → Act → Observe → Adapt** loop (a second Ollama model reviews
each draft and the loop revises until it's approved or a cap is hit). This is the
*runtime* counterpart of [`tools/ai-dev/`](../ai-dev/README.md), which runs the
same loop at build time over repository files.

Full design: [`docs/agentic-ai-workflow.md`](../../docs/agentic-ai-workflow.md).

## The three evidence sinks

Every phase of every run is written to all three:

| Sink | Where | Use |
|---|---|---|
| **stdout** | `logging.getLogger("ai_loop")` → `docker compose logs -f vgarden` / `almanac` | watch the loop live |
| **JSONL** | `tools/ai-loop/logs/<service>.jsonl` (one object per phase) | machine-readable; what `view.py` reads |
| **transcript** | `tools/ai-loop/logs/reports/<service>/<run_id>.md` | human-readable, one file per run |

The in-app chat also shows a `🔄 Plan → Act → Observe → Adapt · N iterations` badge
under each answer, linking to `/…/ai/loop/<id>` which renders the same trace.

## Terminal viewer

```bash
python tools/ai-loop/view.py                    # recent runs, both services
python tools/ai-loop/view.py vgarden-20260903-... # full Plan/Act/Observe/Adapt trace
python tools/ai-loop/view.py --service almanac --last 20
python tools/ai-loop/view.py --follow           # live tail, pretty-printed
```

## Committing evidence

`logs/` is tracked (like `tools/ai-dev/logs/`). Runs accumulate as you use the
chat; commit the specific `<service>.jsonl` lines and `reports/**` transcripts you
want to keep as coursework evidence, and prune the rest. `git add -p` helps.

## Release 1: validate MCP and RAG through the feature

One small terminal runner, two modes, two features (`--feature almanac`, the
default, or `--feature vgarden`). It runs locally, outside Docker, and calls the
feature's own backend; that backend calls the shared MCP or RAG server. It reuses
`shared/ai_loop.py`'s logger and adds no model or server dependency — only
Python's standard library.

### Almanac (public, unauthenticated)

Start the feature and the shared services, enable `MCP_ENABLED` and `RAG_ENABLED`
on the Almanac, and sync the Almanac RAG source using the feature's integration
page first. The starter catalogue must contain Tomato and Powdery mildew.
Then run from the repository root:

```bash
python tools/ai-loop/validate.py --mode mcp --output work/almanac-mcp-validation.json
python tools/ai-loop/validate.py --mode rag --output work/almanac-rag-validation.json
```

The default feature URL is `http://localhost:3000/almanac`. For a direct local
Flask process, add `--base-url http://localhost:5000` (or its actual port).

### Virtual Garden (private per-owner — bootstraps a real session first)

Garden data is private per-owner, so there is no public endpoint to call
anonymously the way Almanac's is. `--feature vgarden` registers a throwaway
account through the *real* browser-facing flow — `POST /auth/register`, create a
garden, follow the SSO handoff into vgarden, seed one area and one Tomato
planting — then runs the same MCP/RAG checks against vgarden's owner-scoped
routes with that session's cookie and CSRF token. No shortcuts: no direct DB
writes, no server-to-server token use from the script itself.

```bash
python tools/ai-loop/validate.py --feature vgarden --mode mcp
python tools/ai-loop/validate.py --feature vgarden --mode rag
```

Requires the stack, the shared MCP/RAG servers, and `MCP_ENABLED`/`RAG_ENABLED`
on vgarden, same as Almanac. The default URLs are `http://localhost:3000/vgarden`
(`--base-url`) and `http://localhost:3000/auth` (`--auth-base-url`); override both
for a direct local Flask process. Registration uses WTForms' email validator,
which rejects RFC 2606 reserved domains (`example.com`/`.test`/…) — the script
uses `@mailinator.com`, a real, publicly documented disposable-inbox domain, so
this needs outbound DNS, same as a real signup through the app. The seeded
account and garden are never deleted; they're harmless throwaway data, the same
way the Almanac checks run against the live catalogue.

Both features: each request has a 120-second timeout and at most two attempts.

The loop is explicit and bounded:

1. **Plan:** bootstrap a session if the feature needs one (vgarden only), then
   choose the two checks for the requested mode.
2. **Act:** send read-only queries through the feature backend.
3. **Observe:** check the actual JSON response. MCP must return usable records
   (plant/disease references for Almanac; the seeded garden's own snapshot/
   plantings for Virtual Garden). RAG must return a cited, grounded answer with
   confidence, scoped to the right record for Virtual Garden (`source_id` must
   match the garden actually asked about — a mismatch means a cross-garden leak),
   and refuse an unrelated question with no answer or citations.
4. **Adapt:** retain successful checks and retry only unavailable requests
   (connection failures, HTTP 429 or 5xx), up to two attempts. Invalid contracts
   fail without disguising the result.

The final JSON reports every check, its received response, the session bootstrap
info (vgarden), and the transcript path. Exit code `0` means all checks passed;
`1` means at least one failed. Phases go to `logs/<feature>.jsonl` and
`logs/reports/<feature>/validate-*.md`, so `view.py` can replay a run as usual.
The runner never calls a write tool beyond the one-time vgarden session seeding
above. A passing result demonstrates the response contract and refusal check, not
that every sentence is factually correct; read the captured answer and cited
excerpts as part of the review.

Amy's CI remains `.github/workflows/plant_almanac.yml`, displayed as **Plant
Almanac (Amy)**; Virtual Garden's is `.github/workflows/vgarden.yml`. Both run on
relevant pull requests/pushes with `MCP_ENABLED=false` and `RAG_ENABLED=false` so
the normal lint, tests and image build do not require live AI services. Live
validation evidence is collected separately with the commands above; CI success
is not a live model result.

## Release 2: review modes (`review.py`)

`review.py` runs the same shared loop over a piece of **Release 2 evidence** and
writes a review/validation log for the technical report (marking criterion 8).
Each mode builds a JSON grounding in code, pins a response schema, runs the
proposer and the independent reviewer on **local Ollama only** at temperature 0,
and refuses rather than guesses. Modes are registered in `MODES` in `review.py`.
The three the assessment asks for (criterion 8) are below; they share the
building blocks `StructuredDrafter` / `GatedReviewer` / `run_structured_review()`
in `shared/ai_loop.py` (ACT with a pinned schema at temperature 0; OBSERVE first
deterministic, then the model reviewer) and the Markdown helpers in
`review_common.py`. Every mode: code computes the facts and the violations first,
the model writes the review from them, the code re-validates the model's output and
enforces the rules whatever it said, and every change the code makes is listed in
the validation log. The findings *are* the code checks: a model finding is kept
only when the code computed the same violation (it then carries the model's wording
and recommendation but the code's severity); one the code did not confirm is
dropped, because every check kind is decided in code and the grounding contradicts
it. When the code had to correct a draft, OBSERVE returns `revise` with the
corrections as guidance before any model reviewer is asked, so the next ACT can fix
them itself; a draft the code found consistent goes to the independent reviewer
model. The small local models invent findings (a missing reason that is recorded, a
citation that "does not align" when it does); this is what keeps those out of the
verdict, and the log shows every one that was removed.

Shared flags: `--model` / `OLLAMA_MODEL` (proposer, default `qwen3:4b-instruct`),
`--review-model` / `OLLAMA_REVIEW_MODEL` (independent reviewer, default
`llama3.1:8b`; `''` for single-shot, logged as `fallback`), `--ollama-url`,
`--auto-pull`, `--max-iterations` (default 2), `--log-dir`, `--copy-dir`,
`--no-copy`, `--output`. Use instruction-tuned, non-thinking models: a thinking
model (e.g. `gemma4`) spends its output budget in Ollama's `thinking` field and
returns empty content. On the CPU-only dev laptop the committed runs used
`--model gemma3:4b --review-model qwen2.5vl:3b`.

Verdicts of the multi-agent and testing modes: `pass` (no high or medium finding;
low ones are informational), `pass_with_findings` (a medium finding),
`fail` (a high finding), `insufficient_evidence` (nothing reviewable; decided in
code, no model call). Only a check computed in code can be high or medium.
Exit codes: `0` pass / pass_with_findings, `1` fail, `2` insufficient_evidence,
`3` the loop could not run. Their validation logs are copied to
`docs/evidence/release2/agentic-review/<mode>-<run stamp>-review.md` / `.json`
(plus `<mode>-latest-review.*`); the cloud mode copies next to its report.

### Multi-Agent Workflow Review (`--mode multi-agent`)

Reviews the evidence the shared Multi-Agent Server exports for a feature
(Planner → Worker → Reviewer → Human Review) and recommends implementation and
review improvements.

```bash
python tools/ai-loop/review.py --mode multi-agent                                                    # Virtual Garden export in docs/evidence/release2
python tools/ai-loop/review.py --mode multi-agent --evidence-dir docs/evidence/release2/local-deployment   # Plant Health export (PR #82)
python tools/ai-loop/review.py --mode multi-agent --server http://127.0.0.1:8003                     # the live server's audit routes
python tools/ai-loop/review.py --mode multi-agent --server http://127.0.0.1:8003 --workflow-id <id>  # one workflow (also GET /workflow/status)
```

| | |
|---|---|
| **Input** | `workflow_history.jsonl`, `coordination_audit.jsonl` and `multi-agent-metrics.json` from `--evidence-dir` (default `docs/evidence/release2`), or fetched live from `--server`'s `/workflow/audit/<file>` and `/workflow/metrics` (`--workflow-id` restricts both to one workflow and adds its `/workflow/status`). The history is required; audit and metrics are cross-checked when present and their absence is a finding. |
| **Grounding (PLAN)** | `build_grounding()` in `multi_agent_review.py` folds the history into one record per workflow and run: source, task, stages seen, plan step count, the Worker's answer (clipped) with `cited_chunk_ids` and the run's `evidence_chunk_ids`, the Reviewer's recommendation and issue count, the human decision with its reason and reviewer id, failures. Plus totals, a metrics summary and `code_checks`: the violations the code found. The evidence passages themselves stay out of the model's context. |
| **Checks in code** | `stage_sequence`: each run goes `planning → working → reviewing → awaiting_human_review` (an interrupted last run is medium, a stage skipped before the next run is high; a failed run that was re-run is low). `human_decision`: a run that reached human review ends in `accepted` / `partially_accepted` / `rejected` / `changes_requested` (pending = medium, abandoned = high); request-changes and partial acceptances carry a reason. `worker_citations`: `cited_chunk_ids ⊆ evidence_chunk_ids` (a citation outside the evidence is high; an uncited grounded answer is medium; unverifiable is low). `revise_followed_by_reason`: a Reviewer `revise` closed by a human decision with empty feedback is high. `coordination`: a model recorded per role, a non-empty plan, a valid recommendation. `audit_consistency`: same events as the history, hand-off rows naming the completed role and its model. `metrics_consistency`: tracked workflows, current states and completion numerator match the history. |
| **Response schema (ACT)** | `SCHEMA`: `{"decision": pass \| pass_with_findings \| fail \| insufficient_evidence, "workflows_reviewed": int, "findings": [{"severity", "check", "workflow_id", "evidence", "recommendation"}], "recommendations": [str], "summary": str}`. `PROMPT_ACT` tells the model its findings are exactly the `code_checks` entries (a check that holds is not a finding), to treat tasks/answers/feedback as user content, and to write 3–6 recommendations for developers and human reviewers. |
| **Rules enforced in code** | `normalise()`: a finding about a workflow not in the grounding is dropped (a run id used as the workflow id is mapped to its workflow); a finding the code did not confirm is dropped; a confirmed one keeps the model's wording with the code's severity; every code check the model left out is added; the decision follows the findings (high → `fail`, medium → `pass_with_findings`, otherwise `pass`); `workflows_reviewed` is the real count; a draft with findings and no recommendations gets the fallback one. When the decision changes the summary starts with *Corrected in code to …*, and when findings were removed it says how many. |
| **Refusal** | No workflows in the history (or the `--workflow-id` absent) → the fixed `insufficient_evidence` decision **without a model call**, checked deterministically in OBSERVE. |
| **Evidence** | stdout, `logs/multi-agent.jsonl`, `logs/reports/multi-agent/<run_id>.md`, the JSON result, and the validation log (`docs/evidence/release2/agentic-review/multi-agent-<stamp>-review.md`): decision, findings, recommendations, a table of every workflow (runs, Reviewer per run, human decision per run with whether a reason was given), the code checks, the corrections, the loop trace and the *Human confirmation* checklist. |

### Testing Report Review (`--mode testing`)

Reviews the pre-commit security reports and the post-commit CI/CD endpoint-testing
reports and recommends testing improvements.

```bash
python tools/ai-loop/review.py --mode testing
python tools/ai-loop/review.py --mode testing --pre-commit-dir docs/evidence/release2/pre-commit --post-commit-dir docs/evidence/release2/post-commit
```

| | |
|---|---|
| **Input** | Pre-commit: every `*.md` except `README.md` under `--pre-commit-dir` (default `docs/evidence/release2/pre-commit`), the pages `scripts/security/report.py` writes (title, *Latest result per check* and *Every recorded run* tables). Post-commit: every folder under `--post-commit-dir` (default `docs/evidence/release2/post-commit`) with `run.json` and the JUnit `endpoints.xml` / `regressions.xml` the feature workflows upload after each push. The `<service>-<student>` stem links a report to a folder. |
| **Grounding (PLAN)** | `build_grounding()` in `testing_review.py`: per report the four checks (result, run time, commit, branch, scope, findings summary) and the run history counts; per folder the workflow, event, commits, run URL, the two endpoint functions, the endpoint test cases with outcomes and the regression counts; the student coverage table; and `code_checks`. |
| **Checks in code** | Pre-commit: each of Ruff `S` rules, detect-secrets, pip-audit and the assigned unit tests present and `PASS` on the latest run (missing or `FAIL` = high). Post-commit: `event = push` (else high); exactly two endpoint functions (else high); `endpoints.xml` present with ≥ 2 tests and no failures/errors (else high) and a test named after each function (else medium); `regressions.xml` present (else medium) and green (else high); `tested_sha = source_sha`, a GitHub Actions run URL, the workflow file in the repo (else medium); a folder README (else low). Coverage: a student with evidence on one side only (medium); a service mismatch between the two sides (low). |
| **Response schema (ACT)** | `SCHEMA`: `{"decision", "students_reviewed": int, "findings": [{"severity", "area": pre_commit \| post_commit \| coverage \| consistency, "subject", "evidence", "recommendation"}], "recommendations": [str], "summary"}`, with the same `normalise()` rules as the multi-agent mode (unknown subjects and unconfirmed findings dropped, omitted code checks added, the code's severity, decision from the findings, count corrected). |
| **Refusal** | No report page and no evidence folder at all → `insufficient_evidence` without a model call. Evidence on one side only is reviewed and the gap is a coverage finding. |
| **Evidence** | stdout, `logs/testing.jsonl`, `logs/reports/testing/<run_id>.md`, the JSON result, and the validation log (`docs/evidence/release2/agentic-review/testing-<stamp>-review.md`): decision, findings, recommendations, one table per evidence kind, the code checks, the corrections, the loop trace and the *Human confirmation* checklist. |

### Cloud Deployment Report Review (`--mode cloud-deployment`)

Reviews the report `scripts/deploy/azure-report.sh` writes at the end of a cloud
deployment and recommends a release decision to the human release manager.

```bash
python tools/ai-loop/review.py --mode cloud-deployment
python tools/ai-loop/review.py --mode cloud-deployment --report docs/evidence/release2/cloud-deployment/cloud-deployment-<stamp>.json
```

| | |
|---|---|
| **Input** | `docs/evidence/release2/cloud-deployment/latest.json` by default, or `--report <path>` |
| **Grounding (PLAN)** | `build_cloud_deployment_grounding()` in `shared/ai_loop.py` selects: commit, branch, workflow run URL, public URLs, the four cloud-baseline flags, container apps (ingress, `allowInsecure`, revision, status, replicas), PostgreSQL public access and backups, key vault RBAC/soft-delete, storage TLS/HTTPS/public-blob/network settings, the smoke result and the claimed security controls. It also computes `evidence_gaps` in code. Bulky sections (`resources`, `platform_outputs`, internal FQDNs) stay out. |
| **Response schema (ACT)** | `CLOUD_DECISION_SCHEMA`: `{"decision": approve \| approve_with_corrections \| reject \| insufficient_evidence, "baseline_compliant": bool, "findings": [{"severity": high \| medium \| low, "area": …, "evidence": …, "recommendation": …}], "release_recommendation": …}`. Pinned through Ollama's `format`, then re-validated and clamped in code (`validate_cloud_decision`, `normalise_cloud_decision`). |
| **Refusal** | No smoke result, or any of the four baseline flags missing → the drafter returns the fixed `insufficient_evidence` decision **without calling the model**, one high finding per gap. |
| **Baseline breach** | Any of `ai_mode_enabled`, `mcp_enabled`, `rag_enabled`, `multi_agent_enabled` true → a high finding in area `cloud_baseline` per switch, `baseline_compliant: false`, and the decision can never be `approve`. A failed smoke test is always `reject`. A finding that claims a switch is on when the grounding has it off is dropped. These rules hold whatever the model said; when they change the decision, `release_recommendation` is prefixed with *Corrected in code to …* and the model's own text is quoted after it. |
| **OBSERVE** | `CloudDeploymentReviewer`: a refusal is checked deterministically (the draft must be the fixed refusal for the computed gaps; the model is not consulted). Every other draft goes to the shared `Reviewer` with `PROMPT_CLOUD_DEPLOYMENT_OBSERVE`: is every finding's evidence in the grounding, is an enabled switch or failed smoke test flagged, does the decision follow the rules. `revise` threads guidance into the next ACT (`carried_feedback`), up to `--max-iterations`. |
| **Models** | `--model` / `OLLAMA_MODEL` (default `qwen3:4b-instruct`), `--review-model` / `OLLAMA_REVIEW_MODEL` (default `llama3.1:8b`; `''` for single-shot, logged as `fallback`), `--ollama-url` / `OLLAMA_URL`, `--auto-pull` / `OLLAMA_AUTO_PULL`. Use instruction-tuned, non-thinking models: a thinking model (e.g. `gemma4`) spends its output budget in Ollama's `thinking` field and returns empty content, so the reviewer call fails and the run is logged as `fallback`. |
| **Evidence** | The three sinks: stdout, `logs/cloud-deployment.jsonl`, `logs/reports/cloud-deployment/<run_id>.md`; the JSON result on stdout (`--output` to save it); and the validation log copied **next to the report** as `cloud-deployment-<stamp>-review.md` / `.json` plus `latest-review.md` / `.json` (`--copy-dir` to redirect, `--no-copy` to skip). The log lists every correction the code made to the model's draft (also `code_corrections` in the JSON) and ends with the *Final human release decision* checklist. |
| **Exit code** | `0` approve / approve_with_corrections, `1` reject, `2` insufficient_evidence, `3` the loop could not run (Ollama unreachable, model missing, invalid model output). |

`python tools/ai-loop/view.py --service cloud-deployment` (or `multi-agent`,
`testing`) replays the runs. Every review is advisory: it supports the team's
confirmation or the release manager's decision on the checklist and does not
replace it.

Tests (fake proposer + scripted reviewer, no Ollama): `tools/ai-loop/tests/test_review.py`
(cloud mode: grounding selection, both refusals, schema validation, the
baseline-breach and failed-smoke rules, feedback threading, all sinks and the
validation log), `test_multi_agent_review.py` (file and live-server loading, every
code check, the refusal, normalisation, the loop and the runner) and
`test_testing_review.py` (report and JUnit parsing on the fixtures under
`tests/fixtures/testing/`, every code check, the refusal, normalisation, the loop
and the runner). Run them from the repository root with
`python -m pytest -q tools/ai-loop/tests`.

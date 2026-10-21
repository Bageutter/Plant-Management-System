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

## Release 2: review modes

Three more `--mode` values review saved evidence rather than calling a feature.
The code is in [`review.py`](review.py); the Release 1 `mcp` and `rag` modes are
unchanged.

| Mode | Reviews | Checks |
|---|---|---|
| `multi-agent` | `workflow_history.jsonl`, `coordination_audit.jsonl` and `multi-agent-metrics.json` exported by the Multi-Agent Server (`--evidence-dir`, default `docs/evidence/release2`) | every run went Planner → Worker → Reviewer → human review in order; every workflow closed by a human; accepting against the Reviewer's advice has a reason; every change request started a new run; every handoff names its model; human reviews from both the UI and the terminal; metrics match the history. **Grounding:** every Worker run was given evidence passages, and each answer cites only passages it was given. **Reviewer:** a verdict on every answer. **Integration (live):** the feature's `/integrations` reports the server as enabled (`--feature-url`, default `http://localhost:3000/vgarden`), and the server answers `/healthz` (`--multi-agent-url`); unreachable counts as missing. `--source vgarden` reviews one feature's workflows. |
| `testing` | for every service (`--services`, all eight by default): the newest pre-commit result of each check in `.security-reports/`, the test results, log and endpoint coverage saved by `scripts/test/collect-test-evidence.py` (`--test-evidence`), the newest finished run of each GitHub Actions workflow on `main` (`--workflows`), and optional downloaded CI JUnit files (`--ci-evidence`) | each pre-commit check passed; each service's tests pass (failures, errors, skipped, log warnings); every endpoint is run by a test, measured with coverage.py, so a URL that is only mentioned doesn't count (`warn` with the untested endpoints listed); each workflow's latest run succeeded; `--endpoint-workflows` ran their endpoint test step |
| `cloud-deployment` | `docs/evidence/release2/cloud-deployment/latest.json` from `scripts/deploy/azure-report.sh` (`--grounding`), the live site (`--url`, default the report's `app_url`) and the `cloud-deployment.yml` runs | AI-Mode, MCP, RAG and Multi-Agent disabled in the cloud baseline; the deploy's smoke test passed; container apps running with one public entry; database not public; the deployed commit passed CI; HTTPS; the same paths as `azure-smoke.sh` respond |

Each run is one bounded loop:

1. **Plan:** collect the evidence and run the checks above. No model is involved.
   A check is `pass`, `warn` (needs work but doesn't block, such as an untested
   endpoint), `fail` or `missing`. Missing evidence is never a pass, and neither is
   GitHub being unreachable.
2. **Act:** the local Ollama model (`--model`, default `qwen3:4b-instruct`) drafts
   a review from those facts only, at temperature 0 with a pinned JSON schema:
   summary, findings tied to check IDs, recommendations, and a verdict
   (`ready`, `ready_with_fixes`, `not_ready`).
3. **Observe:** fixed rules first. The draft may cite only real check IDs, must
   raise every failing or missing check as major or blocker, and can't say
   `ready` while any check isn't passing. Then a second model
   (`--review-model`, through `shared/ai_loop.Reviewer`) checks that every
   statement is supported by the facts.
4. **Adapt:** feed the problems back and redraft, up to `--max-iterations` (2).
   If the last draft still breaks the rules, the review is written from the
   checks alone, so the verdict never goes beyond the evidence. The same happens
   with `--no-model` or when Ollama is down, and the log says so.
5. **Human review:** you record the decision: `accept` / `partially_accept` /
   `reject`, or `release` / `hold` / `rollback` for `cloud-deployment`. It's
   asked in the terminal, or passed with `--decision` and `--reason`; without
   either and without a terminal it's recorded as `pending`.

```bash
python3 tools/ai-loop/validate.py --mode multi-agent --output docs/evidence/release2/review-multi-agent.json
python3 scripts/test/collect-test-evidence.py      # tests + endpoint coverage, every service
python3 tools/ai-loop/validate.py --mode testing --output docs/evidence/release2/review-testing.json \
    --report docs/evidence/release2/testing-review.md
python3 tools/ai-loop/validate.py --mode cloud-deployment --output docs/evidence/release2/review-cloud-deployment.json
```

The review/validation log for each run is in the usual places:
`logs/review-<mode>.jsonl` and `logs/reports/review-<mode>/<run_id>.md`. The
`--output` JSON holds the checks, the facts the model saw, the review, which
step the verdict came from, and the human decision. Exit code `0` means every
check passed.

The `testing` and `cloud-deployment` modes read GitHub Actions through its public API,
which allows 60 requests an hour without signing in (one `testing` run uses about 14).
Set `GITHUB_TOKEN` to a read-only token to raise that to 5,000; it is only sent to
`api.github.com`. When the API is unavailable, those checks are `missing`, never `pass`.

Tests (fake model and evidence, no Ollama or GitHub; also run in `vgarden.yml`):

```bash
python3 -m unittest discover -s tools/ai-loop/tests
```

## Release 2: Cloud Deployment Report Review (`cloud_report_review.py`)

The report-level review of a cloud deployment, implemented **inside the shared
loop** (`shared/ai_loop.py`) and run from the terminal. It complements
`validate.py --mode cloud-deployment` above: that mode scores the deployment with
fixed checks (report, live probes, workflow runs) and records the human decision;
this one has the loop read the report itself with a pinned decision schema,
refusal and baseline-breach rules, and writes a validation log next to the report
for the release manager. Both run on local Ollama only; they log to different
services so `view.py` keeps them apart.

```bash
python tools/ai-loop/cloud_report_review.py
python tools/ai-loop/cloud_report_review.py --report docs/evidence/release2/cloud-deployment/cloud-deployment-<stamp>.json
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

`python tools/ai-loop/view.py --service cloud-deployment` replays the runs. The
review is advisory: it supports the release manager's decision on the report's
checklist and does not replace it. Tests: `tools/ai-loop/tests/test_cloud_report_review.py`
(fake proposer + scripted reviewer: grounding selection, both refusals, schema
validation, the baseline-breach and failed-smoke rules, feedback threading, all
sinks and the validation log); they run with the `unittest discover` command above.

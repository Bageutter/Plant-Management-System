# Closing the Release 2 criteria — Amy's completion branch

Branch: `amy/release2-completion`, based on main `7dbd213`. These changes are
prepared for review; they are not a deployment or a claim of awarded marks.

## Verified checkpoint

Selected files downloaded from GitHub Actions on 22 October (deployment summary is labelled as a read-back):

| File | Source | Actual result |
| --- | --- | --- |
| [baseline-deployment.md](baseline-deployment.md) | [baseline run 39743232141](https://github.com/Bageutter/Plant-Management-System/actions/runs/39743232141), commit `7dbd213` | Deploy/smoke pass; all four AI flags off at that checkpoint |
| [baseline-security.json](baseline-security.json) | Same run, security validation artifact | 17/17 pass for endpoint/data controls |
| [bonus-ai-failed.txt](bonus-ai-failed.txt) | [bonus run 39745279626](https://github.com/Bageutter/Plant-Management-System/actions/runs/39745279626), same source commit | 3/7 pass; AI-Mode timeouts, no RAG citations, failed Multi-Agent planning |

The original bonus job was green because its `python ... | tee ...` command
lost Python's failure exit code. The branch fixes that with explicit Actions
Bash (`-eo pipefail`) and a regression that executes both actual workflow run
blocks with a failing validator. The security JSON and bonus transcript are unchanged; the deployment Markdown is a labelled summary of the source artifact.

Read-only live checks during this branch's work returned 200 from all three
feature integration endpoints, with MCP/RAG/Multi-Agent **enabled**. The site
currently reflects the later bonus profile, not the earlier baseline. Do not
describe the saved baseline configuration as current live state.

## What the branch fixes

- Criteria 5–7: baseline deployments run the full public-URL CRUD validator after
  smoke checks. It checks baseline flags before any writes, verifies saved edits
  with separate GETs, checks deletion, and saves per-check JSON and console output.
- Health's integrations endpoint exposes the actual `AI_MODE_ENABLED` setting,
  so the validator can reject a non-baseline deployment without a model call.
- Generated deployment reports include a separate CRUD result. A different SHA,
  run, target or prior-day result is labelled unverified. The manual deployment
  script also runs CRUD and exits nonzero on failure.
- Cloud Review now checks that CRUD passed for its deployment's SHA/run/target;
  page availability alone cannot satisfy the new `CD-CRUD` check.
- Criterion 9: repository report corrects historical/current cloud claims,
  preserves the failed bonus result, and remains below 3,000 whitespace words.
  The native Google Doc and final PDF are separate artifacts and were not edited.

## What is required for 3/3

| Criterion | Concrete completion evidence | Remaining action / owner |
| --- | --- | --- |
| 1 Local integration | Existing three-feature local evidence plus final local CRUD/AI/MCP/RAG/Multi-Agent walkthrough | Each student demonstrates their feature; this cloud patch does not replace it |
| 2 Multi-Agent | Existing terminal/UI workflow histories, audit exports, reviewer and real human decisions | Confirm final integrated UI run and show it in the video; all members |
| 3 Security hooks | Existing individual actual-commit evidence and passing security reports | Include the per-member evidence in the submitted report |
| 4 Endpoint CI | Each named two-function test step passes at the chosen SHA | Keep the three matching run links/artifacts in the report |
| 5 Cloud scripts | Script execution plus deployment facts for the chosen revision | Deploy/revalidate this branch after review; deployment owner |
| 6 Cloud CI/CD | Gates, deploy, smoke and new CRUD step all pass; artifact retained | A successful baseline run containing these changes is still needed |
| 7 Cloud CRUD | New CRUD JSON: all checks pass, target/SHA/run match the deployment; baseline AI flags off | Restore baseline, run the workflow and demonstrate each feature's UI and persisted edits |
| 8 Review modes | All three review reports and logs use the chosen final evidence | Refresh Cloud Review after the new baseline run; actual people record Multi-Agent acceptance and release/hold/rollback with reasons. Testing acceptance already exists |
| 9 Report | Correct final checkpoint, all diagrams/contributions/evidence, group PDF <=3,000 words | Amy confirms her contribution; group reconciles Google Doc, exports and visually checks PDF |
| 10 Showcase | Published <=10-minute video URL, all members demonstrate and explain contributions | Record/publish with the existing shot list; all members |

This checklist follows the actual three-point rubric bands; no code change can
guarantee a tutor's mark or substitute for a recording or a human decision.

## Validation performed on this branch

- Health: **107 tests passed**, including both AI-Mode configuration states.
- Deployment: **5 stdlib regression tests passed**, covering missing/enabled flags,
  refusal before account creation, failure JSON, stale provenance and pipeline exits.
- Shared review modes: **58 tests passed**, including failed/missing/mismatched
  CRUD evidence being retained as a Cloud Review gap.
- Ruff normal and security checks, Bash syntax checks and `git diff --check`.
- No production CRUD writes, cloud deployment, model calls or human decisions were
  performed to produce these results. No bonus AI marks are established here.

After a reviewed baseline deployment, download its report artifact, check
`e2e-crud.json` has `result=pass` and the correct SHA/run/target, retain it, then
run `tools/ai-loop/validate.py --mode cloud-deployment --grounding <that-report.json>`.
Read the output before the human release decision. Record the final demonstration
and report links only after those steps succeed.

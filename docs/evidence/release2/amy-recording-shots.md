# Amy's recording shots — Plant Almanac

Use these shots inside [the group video script](video-script.md), not as another
video added afterwards. Amy covers Almanac, the shared Multi-Agent Server and
security tooling, her endpoint CI, and demonstrates the shared review modes.
Demonstrating a shared mode does not claim authorship of every review mode.

Keep the complete group video under ten minutes. Film short clips, remove model
waiting time in editing, and keep the same workflow/run identifiers visible.
The spoken lines are in the group script; this page defines the camera actions.

## Before recording

- Sign in on the local and cloud applications. Chat is unavailable when logged out.
- Keep the address bar visible so local and cloud footage are distinguishable.
- Use a harmless, agreed demo record for edits. Do not expose passwords or cookies.
- Have Ollama, MCP, RAG and the Multi-Agent Server running as host processes;
  the application containers are separate. Confirm the Almanac's Multi-Agent mode is enabled.
- Index current Almanac references before a retrieval demonstration. In Reference
  tools, expand **Updated the catalogue?** and use **Refresh references**.
- Prepare one actual intended commit for the hook clip, or its genuine saved
  terminal recording. Inspect staged files; do not stage unrelated work.
- Open a successful `plant_almanac.yml` run with its SHA and test artifact.

## Shot list

| Shot | Screen framing | Exact action | What the viewer must see before cutting |
| --- | --- | --- | --- |
| **A1 Local Almanac** | Browser, local URL and plant card | Search `tomato`, open the plant, **Edit**, change one field, save, reload | Saved value still visible after reload; identify this as local CRUD |
| **A2 AI validation report** | Chat, then opened report dialog | Open **Ask the Almanac**, choose **Planning**, ask a question supported by the catalogue. Beneath an answer that has a saved loop run, click **View validation report →** | **Answer validation report** is open with the recorded Plan/Act/Observe/Adapt trace; briefly scroll if entries are below the fold |
| **A3 Multi-Agent answer** | Chat question, answer and source panel | Close the report, choose **Multi-Agent**, ask `Tomato planting months`; after completion expand **How the agents approached this** and **Check the saved facts** | Plan, actual answer, cited saved facts, and either **Changes recommended** or **Ready for your check** |
| **A4 Human decision** | Decision form and revised answer | For a real revision, choose **Request changes**, enter `Also give the scientific name and family of Tomato, only if recorded in the sources.`, click **Save my review**, then **Run agents again**. Read the result and make your own final choice | Revised result, your feedback, and **Your saved decision**. Choose **Accept answer**, **Accept only part**, or **Reject answer** to match what you checked |
| **A5 Server and audit** | Brief editor cut, then server dashboard | Show `planner.py`, `worker.py`, `reviewer.py`, `human_review.py` and `audit.py`; open `http://127.0.0.1:8003/dashboard` | Matching workflow ID/state and **Execution history ↓** / **Coordination audit ↓** links. Show an export with stages and hand-offs; do not imply the old snapshot is this new run |
| **A6 Commit hooks** | Terminal with command, results and commit identity | Commit the inspected intended change through normal hooks; hold the four results. Then show the full-service scan report separately | Ruff security, detect-secrets, pip-audit, assigned tests, and the actual successful commit. Explain any failure honestly rather than bypassing it |
| **A7 Endpoint CI** | GitHub Actions job, then artifact | Open **Plant Almanac (Amy)** → successful run → **Test the two assigned endpoint functions**; open/download its evidence artifact | `catalogue_api.search` and `catalogue_api.plant` tests, successful results, matching SHA/run metadata, and `endpoints.xml` or `endpoints.log` |
| **A8 Cloud Almanac** | Browser with full public cloud hostname | On the required baseline deployment, open a demo plant, edit one field, save and reload | Updated value persisted through a fresh read. Show or pair with baseline integration flags; this is cloud footage, not local footage |
| **A9 Multi-Agent Review** | Terminal command, then Markdown report/JSON and log | Run the Almanac-scoped command in the group script. Inspect its report, checks and validation transcript; enter your actual decision in the terminal | Input evidence scope, model/rule results, output report, validation log and real human decision/reason; `pending` means not yet decided |
| **A10 Other review modes** | Each command and its own report/log | Run **Testing Review** with security + endpoint CI evidence; run **Cloud Deployment Review** with the final deployment + validation evidence | All three modes have been shown across A9/A10. The group Testing Review must cover all members; an Almanac-only review is narrower |

## The validation report is an opened view, not always-visible text

The link is rendered beneath an assistant message **only when that message has a
saved loop run**. Its status can be **Answer checked**, **Review limit reached**
or **Review unavailable**. The **View validation report →** action opens a dialog;
the report is not expanded in every chat answer. The trace is scoped to the
signed-in chat owner. MCP/RAG and Multi-Agent have their own evidence displays.

Use this narration:

> For answers processed by the agentic loop, I can open the validation report to
> inspect its Plan, Act, Observe and Adapt stages.

Do not say “each answer carries a report” or call a review unavailable/capped
result approved. If the link is missing, confirm you are signed in and looking
at a completed Planning answer with a saved run; do not invent the missing trace.

## Keep these three concepts separate

1. **Plant-answer loop report:** A2 inspects a saved Plan/Act/Observe/Adapt run.
2. **Workflow's Reviewer agent:** A3–A4 checks a Worker's plant answer; the user
   then makes the final workflow decision.
3. **Assignment Multi-Agent Review mode:** A9 reviews exported workflow history
   and coordination evidence and writes a separate report and validation log.

The A9 command reviews `docs/evidence/release2/almanac-multi-agent/`. It does not
automatically export the live workflow filmed in A3. Show that saved scope, or
export the new matching history/audit/metrics before choosing them as inputs.
Similarly, a report describing a previous deployment does not prove the current
cloud configuration. Refresh evidence against the selected final checkpoint.

## If a run fails

- No relevant source: show the refusal and explain that it avoids guessing.
- Reviewer raises a concern: inspect the cited facts and request correction or
  make a justified partial/reject decision. Do not accept just for the camera.
- A review remains pending: say pending. Read it before recording a decision;
  never prefill `accept` or `release` to make a demonstration look complete.
- Cloud baseline flags are enabled, or matching CRUD evidence is missing: finish
  deployment validation before claiming Cloud Review is ready.
- The full edit is too long: shorten code scrolling and optional bonus footage;
  keep the required UI, individual testing and all three review-mode evidence.

Before publishing, time the complete group edit, ensure everyone speaks and can
defend their own work, and put the signed-out-accessible video URL in the report.

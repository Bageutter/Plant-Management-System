# Release 2 showcase video script (9 minutes, ~120 wpm)

Written against the Assessment 3 brief. The video must show, through the frontend UI: the
Multi-Agent workflow, the UI running locally **and** in the cloud, pre-commit security scans,
post-commit CI/CD endpoint tests (two endpoint functions per student, in that student's own
workflow file), and the agentic-loop review modes. All three students must appear, each
must explain their own Release 2 contribution, and each must show their own feature in the
cloud deployment as well as locally. Maximum length is 10 minutes; this script targets
about nine, including the bonus section (AI services and security in the cloud).

Speakers: **Yunus** (Virtual Garden, auth, proxy, local and cloud deployment),
**Amy** (Plant Almanac, shared Multi-Agent Server, shared security tooling, review demonstration),
**Guhan** (Plant Health).

Conventions: `[square brackets]` are what the screen shows or what the presenter clicks.
Bold name = who speaks the lines underneath. Times are cumulative targets. The blockquoted narration totals about 1,010 whitespace words (about 8.4 minutes at 120 wpm), excluding screen actions. Rehearse the complete edit and cut the optional bonus before required evidence if needed to stay below ten minutes.

## Before recording (not spoken)

1. Five host terminals, tiled so they fit one screen: `ollama serve`; `python ai-services/mcp-server/server.py`; `python ai-services/rag-server/app.py`; `cd ai-services/multi-agent-server && python app.py`; and `docker compose up -d --build`. Start the Almanac with `MULTI_AGENT_ENABLED=true` so its Multi-Agent tab is live (compose defaults it off for almanac only). On the Windows/WSL laptop, `scripts/demo/wsl-demo-up.sh` starts all of this detached and `scripts/demo/open-terminals.cmd` opens one Windows Terminal window with the five live logs plus a shell for the demo commands.
2. Models pulled and warm: `qwen3:4b-instruct` and `qwen2.5vl:3b` (every role in `docker-compose.demo.yml` and `wsl-demo-up.sh` uses one of these two, so `llama3.1:8b` is not needed). On the Windows/WSL laptop they run as the `-demo` variants, created once with `bash scripts/demo/create-demo-models.sh`. Ask each one something once before recording.
3. A sixth terminal with these typed and ready: `bash scripts/test/local-deployment-check.sh`, `bash scripts/test/multi-agent-health.sh`, and the three review commands from `tools/ai-loop/README.md` (`validate.py --mode multi-agent`, `--mode testing`, `--mode cloud-deployment`). Run the reviews in an interactive terminal, read each result and enter the actual human decision with a reason. Do not preselect acceptance or release for the camera. The committed `multi-agent-review.md` and `cloud-deployment-review.md` still say pending; retain the new reports/logs after the real decisions. A failing or incomplete review must be described honestly.
4. A registered account on the local site and one on the deployed site, both logged out, so each login is shown live.
5. Garden **Backyard** (Melbourne, Australia) with area **North bed** and plantings **Basil ×6 (Sown)**, **Tomato (Roma) ×3 (Growing)**. Click **Sync this garden to the knowledge base** once.
6. Plant Health: plant name **Tomato in the back bed** with two or three earlier assessments. Click **Sync records to the knowledge base** once. One clear photo of a plant with yellowing leaves on the desktop.
7. Almanac opened once so the seed catalogue has loaded, then, while logged in, on **Reference tools** expand **Updated the catalogue?** and click **Refresh references** once so the RAG server has indexed the catalogue (otherwise "Ask with sources" answers "insufficient context").
8. Browser tabs ready: GitHub **Actions** filtered to each of `vgarden.yml`, `plant_almanac.yml`, `health.yml` and `cloud-deployment.yml` (one green run each, opened at the "Test the two assigned endpoint functions" step); the Azure portal resource group `rg-plantms-prod`; the deployed proxy URL from `docs/evidence/release2/cloud-deployment/latest.md`; `http://127.0.0.1:8003/dashboard`.
9. Record the **bonus** section (7:15) first, while the deployed site is on the bonus profile: `curl <deployed URL>/vgarden/integrations` reports `"enabled": true` for `mcp`, `rag` and `multi_agent`. If it is on the baseline, `gh workflow run cloud-deployment.yml -f profile=bonus -f ai_min_replicas=1 -f service_min_replicas=1` (approved in `azure-production`) brings the AI apps up; Ollama's models are already on the file share. On the deployed site, log in, open a garden with a planting and click **Sync this garden to the knowledge base** about a minute before the RAG question. Each cloud model answer takes one to three minutes on CPU, so cut the waits. Then switch to the baseline for the cloud shot as in step 10.
10. The deployed site must be on the **baseline** profile for the cloud shot: `curl <deployed URL>/vgarden/integrations` must report `"enabled": false` for `mcp`, `rag` and `multi_agent`. A bonus-profile run leaves them enabled. `gh workflow run cloud-deployment.yml -f service_min_replicas=1`, approved in `azure-production`, puts the baseline back in 6–10 minutes and keeps every service warm so the first click is instant; run it again without `-f` after recording to scale back to zero.
11. A one-line change staged so a commit can be shown running the pre-commit hooks.
12. Record the model waits in full, then cut them in editing. On CPU the garden workflow, the health assessment and the review modes can each take one to three minutes; with the models on a GPU a Planner, Worker, Reviewer run takes about 15 to 25 seconds and a chat answer 5 to 10 seconds.
13. If any container is recreated (for example after a compose change), restart the proxy too: nginx caches each backend's IP at startup and otherwise answers 502.
14. On the Windows/WSL laptop, `docker-compose.demo.yml` holds the recording settings and the rerun steps are in its header comment.

---

## 0:00 – Introduction and local deployment (≈95 words)

`[Open http://localhost:3000/ — the landing page, hero "A living digital model of your garden."]`

**Yunus**
> This is the Plant Management System, a microservice application for small home gardens. Six containers run under Docker Compose: a proxy, the frontend, auth, and the Virtual Garden, Almanac and Plant Health services, each with its own database.

`[Switch to the tiled terminals: Ollama, MCP server, RAG server, Multi-Agent Server, compose.]`

> The AI services are not containers. AI-Mode on Ollama, the MCP server, the RAG server and the Release 2 Multi-Agent Server each run as a local process, and the UI reaches them only through each service's backend.

`[In the sixth terminal run the local deployment check. Scroll to the final line: all checks pass.]`

> The deployment check confirms every container and every host service is up and reachable from inside the containers.

## 0:45 – Virtual Garden: CRUD, Release 1 AI and the Multi-Agent workflow (≈155 words)

`[Click "Log in". Enter the demo account. Click "Log in". Land on /auth/account.]`
`[Click "+ Add a garden". Name "Balcony", location "Sydney, Australia". Click "Create garden". Then click the "Backyard" card.]`

**Yunus**
> My feature is Virtual Garden, the source of truth for each garden. Auth creates the garden through the Virtual Garden API and signs us in with a token.

`[Click "+ Add planting". Crop "Lettuce", quantity 4, area "North bed", lifecycle "Sown". Click "Add planting". The table updates in place.]`

> Areas, containers and plantings are full CRUD; HTMX swaps the table without a reload.

`[Scroll to "Tools" with the "MCP on" badge. Choose "get_garden_snapshot". Click "Run tool". Then in "Ask about this garden (grounded)" type "What is planted in the North bed?" and click "Ask".]`

> The Release 1 panels are retained: an MCP tool returns a structured snapshot, and the RAG panel answers from this garden's indexed records with a confidence badge and sources. Both are owner-scoped, so a question is never grounded in someone else's garden.

`[Scroll to "Agent workflow (Planner → Worker → Reviewer → you)". Type "Summarise what is planted in each area and what is due for harvest". Click "Start workflow". Stage chips light up; cut the wait.]`

> This is the Release 2 integration. Virtual Garden sends the task and this garden's records as evidence to the shared Multi-Agent Server. The Planner writes the steps, the Worker answers only from the evidence and cites passage IDs, and the Reviewer checks the answer against the same records.

`[Show the finished card: Planner steps, Worker answer with "Cited:", Reviewer recommendation and issues. In "Your review" choose "Request changes", type "Mention the lettuce sown today", click "Submit review". The revised run starts; cut the wait; choose "Accept", submit.]`

> The human closes every workflow. Requesting changes feeds my comment back to the Planner and Worker for a revised run, which I then accept.

## 2:05 – Plant Almanac and the Multi-Agent Server

Amy's precise click order, framing and visible proof are in
[amy-recording-shots.md](amy-recording-shots.md), shots A1–A5. Keep the browser
URL visible and cut model waits, not the source-checking or decision.

`[A1: Signed in on the local Almanac. Search tomato, open its card, edit one field, save and reload to show the saved value.]`

**Amy**
> I own the Plant Almanac: a public plant, pest and disease catalogue with CRUD for plant records. Its MCP and RAG reference tools are reached through the Almanac backend.

`[A2: Open Ask the Almanac in Planning mode. Ask a supported catalogue question. Beneath an answer with a saved loop run, click View validation report →. Hold the open Answer validation report dialog on its Plan/Act/Observe/Adapt entries. Do not assume the link always says Answer checked.]`

> For answers processed by the agentic loop, I can open the validation report to inspect its Plan, Act, Observe and Adapt stages.

`[A3–A4: Close the report. Choose Multi-Agent; ask Tomato planting months. After it finishes, open How the agents approached this and Check the saved facts. Point to the actual answer, sources and review concerns. Show the revision controls and make a decision based on those facts, then hold Your saved decision.]`

> I also implemented the shared Multi-Agent Server. The Planner defines the work, the Worker retrieves Almanac evidence through MCP and RAG, and the Reviewer checks the draft. I check the saved facts before deciding. The same server coordinates all three features and records its stages and decisions.

`[A5: Brief editor/dashboard cut: planner.py, worker.py, reviewer.py and audit.py; then the matching workflow ID and Execution history / Coordination audit exports. Do not linger on code.]`

## 3:15 – Plant Health: the workflow through the UI and the terminal (≈180 words)

`[Click "Plant Health". Choose "Tomato in the back bed", type "Lower leaves turning yellow, soil stays wet", upload the photo, click "Assess plant health". Stages stream; cut the wait. Show the result card.]`

**Guhan**
> My feature is Plant Health. An assessment is created from a photo and description by a local vision model, with a status, score, issues and actions. The assessment itself runs an agentic loop: Perceive, Reason, Act, Observe, Repeat, with code checks and a second reviewer model on every draft. The Release 1 MCP tools and the RAG panel over your records are retained below the form.

`[Click "View full record →". Scroll to the record's "Agent workflow" panel. Type "Which issues need attention first, and has this plant got better or worse?". Click "Start workflow". Cut the wait. Show Planner, Worker, Reviewer. In "Your review" the four options are "Accept", "Partially accept", "Request changes" and "Reject": choose "Partially accept", type "The priority order is right; the better-or-worse claim needs a newer assessment", click "Submit review". The card shows "partially accept" with the reason.]`

> The Release 2 panel on each record sends this plant's stored assessments as evidence, never another plant's. The Worker may not add causes or treatments that are not in them, and the Reviewer flags anything unsupported before I decide. The human decision is approve, correct, partial acceptance or rejection: here I keep the priority order but not the trend claim, and the server records that with my reason. The workflow row is deleted with the assessment, and the off switch keeps it out of CI and the cloud.

`[Switch to the terminal. Run the multi-agent health script. It prints each stage, then asks for the decision; type "accept".]`

> The same workflow runs from the terminal through the same backend API.

`[Open http://127.0.0.1:8003/dashboard.]`

> The server's dashboard lists every workflow and exports the workflow history and coordination audit logs that are in our report.

## 4:35 – Pre-commit security and post-commit CI/CD testing (≈95 words)

`[Terminal: run `git commit` on the staged change. The hooks run: Ruff, detect-secrets, pip-audit, pytest.]`

**Amy**
> I implemented the shared pre-commit tooling. On an actual commit it runs Ruff security checks, detect-secrets, pip-audit and the assigned service tests. A failing check blocks that commit.

`[A6: Hold the actual commit command, commit identity and all four hook results. Then open docs/evidence/release2/pre-commit-all-services.md. This is a separate full scan, not proof that another commit happened.]`

> This separate report scans every tracked file of each service; it supports the commit evidence.

**Yunus**

`[GitHub Actions: open the green run of "Virtual Garden (Yunus)", expand "Test the two assigned endpoint functions".]`

> After each push my workflow tests two endpoint functions, create garden and garden snapshot, and uploads the JUnit results as an artefact.

`[A7: Open the successful Plant Almanac (Amy) run; keep its SHA visible. Expand Test the two assigned endpoint functions, then show the retained endpoints.xml/endpoints.log artifact.]`

**Amy**
> My two functions are catalogue_api.search and catalogue_api.plant. They test search, pagination, invalid requests, source fields and that reads make no database changes. This artifact retains the endpoint results.

`[Open the green run of "Plant Health (Guhan)", same step.]`

**Guhan**
> Mine tests create assessment and list assessments, then runs the remaining regression suite and the compose smoke test with the AI switched off.

## 5:20 – Cloud deployment: every feature in Azure (≈145 words)

`[Open the green "cloud-deployment.yml" run. Show the gate jobs, then the Bicep and deploy steps. Switch to the Azure resource group.]`

**Yunus**
> A green main triggers the cloud deployment workflow. After the CI gates pass, Bicep provisions the registry, Key Vault, network and six container apps, and the reusable deploy scripts push the same images we run locally, with PostgreSQL in place of SQLite.

`[Open the deployed URL. Log in, click "+ Add a garden", create "Cloud test", open it, add a planting. Scroll to the panels: "MCP off", "RAG off", "Multi-Agent off".]`

> The same UI and CRUD work in Azure. As the brief requires, AI-Mode, MCP, RAG and the Multi-Agent Server are disabled by default in the cloud, and the deploy scripts are reusable: the same script that GitHub Actions runs deploys from a laptop after an Azure login.

`[A8: Keep the cloud hostname visible. Open Almanac, search tomato, open its card, Edit, save one field, then reload and show the persisted value. Use an agreed demo record and the AI-off baseline.]`

**Amy**
> The Almanac catalogue and its CRUD run on PostgreSQL in Azure with the same templates; the chat and reference tools are switched off here, as the baseline requires.

`[Click "Plant Health". Choose "Other / new plant…", type "Cloud tomato", description "Lower leaves yellowing", click "Assess plant health". The record is saved at once; its summary starts "Not assessed." and names AI-Mode as off.]`

**Guhan**
> With AI-Mode off, Plant Health still saves the record, marked not assessed, so create, read, update and delete work without a model; "Generate report again" assesses it later wherever AI-Mode is on.

## 6:35 – Agentic-loop review modes (≈75 words)

`[A9: Show the exact Multi-Agent Review command below. Run it, cut the model wait, then open the generated report and validation log. Frame the input source, checks, model verdict and actual Human decision together.]`

```bash
recording_dir="docs/evidence/release2/amy-recording-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$recording_dir"
python3 tools/ai-loop/validate.py --mode multi-agent --source almanac \
  --evidence-dir docs/evidence/release2/almanac-multi-agent \
  --feature-url http://127.0.0.1:3000/almanac \
  --multi-agent-url http://127.0.0.1:8003 --reviewer-id amy \
  --model qwen3:4b-instruct --review-model qwen3:4b-instruct \
  --log-dir "$recording_dir/logs" --output "$recording_dir/review.json" \
  --report "$recording_dir/review.md"
```

**Amy**
> This separate Multi-Agent Review checks saved workflow history and coordination evidence, not a plant answer. It collects checks, drafts a review with local Ollama, independently reviews that draft and revises it when needed. Here are its report, validation log and my actual decision.

`[If Human decision is still pending, say pending instead of claiming a decision. The command reviews saved Almanac exports, not automatically the new workflow just filmed. Export that workflow first if it is the intended input.]`

`[A10: Run Testing and Cloud Deployment Review modes too, each against its selected evidence. Show each mode's input, output and validation log, rather than only opening one report.]`

> Testing Review reads security and endpoint CI evidence. Cloud Deployment Review reads deployment and validation evidence. Each saves a report and log. The model recommendation and the final human decision are separate.

## 7:15 – Bonus: AI services and security in the cloud (≈110 words)

`[Deployed site (bonus profile), open the garden. In "Tools" (badge "MCP on") choose "get_garden_snapshot", click "Run tool". In "Ask about this garden (grounded)" type "What is planted in the North bed?", click "Ask".]`

**Yunus**
> For the bonus, an opt-in deploy profile runs AI-Mode, MCP, RAG and the Multi-Agent Server in Azure as four internal-only container apps, reached only through each feature's backend. Here the MCP tool and the grounded RAG answer come from the cloud.

`[In "Agent workflow (Planner → Worker → Reviewer → you)" type "Summarise what is planted in each area", click "Start workflow". Cut the wait. Choose "Accept", click "Submit review".]`

> The full Planner, Worker, Reviewer and human-review workflow runs on the cloud model too.

`[Terminal: curl -sI <deployed URL> — the security headers. Then open docs/evidence/release2/cloud-security/latest.md, "17/17 controls pass".]`

> For security, the proxy is the only public endpoint. It adds HSTS and a content security policy, and rate-limits sign-in. The database is private to the network, secrets live in Key Vault, and GitHub signs in without stored credentials. All 17 checks pass.

## 8:15 – Close (≈40 words)

`[Return to the local landing page.]`

**Guhan**
> To recap: an integrated application running locally and in Azure, a Multi-Agent workflow through every feature's UI and the terminal, security scans on every commit, endpoint tests on every push, and reviews of our own release. Thanks for watching.

`[Hold for two seconds. End.]`

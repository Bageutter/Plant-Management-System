# Release 2 showcase video script (8 minutes, ~120 wpm)

Written against the Assessment 3 brief. The video must show, through the frontend UI: the
Multi-Agent workflow, the UI running locally **and** in the cloud, pre-commit security scans,
post-commit CI/CD endpoint tests (two endpoint functions per student, in that student's own
workflow file), and the agentic-loop review modes. All three students must appear, each
must explain their own Release 2 contribution, and each must show their own feature in the
cloud deployment as well as locally. Maximum length is 10 minutes; this script targets
eight so there is room for Q&A.

Speakers: **Yunus** (Virtual Garden, auth, proxy, local deployment, pre-commit, cloud
deployment), **Amy** (Plant Almanac, Multi-Agent Server, agentic-loop review modes),
**Guhan** (Plant Health).

Conventions: `[square brackets]` are what the screen shows or what the presenter clicks.
Bold name = who speaks the lines underneath. Times are cumulative targets. Spoken text is
about 960 words, which is eight minutes at 120 words per minute; cut the model
waits in editing so the clicks and page loads do not push it past nine.

## Before recording (not spoken)

1. Five host terminals, tiled so they fit one screen: `ollama serve`; `python ai-services/mcp-server/server.py`; `python ai-services/rag-server/app.py`; `cd ai-services/multi-agent-server && python app.py`; and `docker compose up -d --build`. Start the Almanac with `MULTI_AGENT_ENABLED=true` so its Multi-Agent tab is live (compose defaults it off for almanac only). On the Windows/WSL laptop, `scripts/demo/wsl-demo-up.sh` starts all of this detached and `scripts/demo/open-terminals.cmd` opens one Windows Terminal window with the five live logs plus a shell for the demo commands.
2. Models pulled and warm: `qwen3:4b-instruct` and `qwen2.5vl:3b` (every role in `docker-compose.demo.yml` and `wsl-demo-up.sh` uses one of these two, so `llama3.1:8b` is not needed). On the Windows/WSL laptop they run as the `-demo` variants, created once with `bash scripts/demo/create-demo-models.sh`. Ask each one something once before recording.
3. A sixth terminal with these typed and ready: `bash scripts/test/local-deployment-check.sh`, `bash scripts/test/multi-agent-health.sh`, and the three review commands from `tools/ai-loop/README.md` (`validate.py --mode multi-agent`, `--mode testing`, `--mode cloud-deployment`). Pass the human decision on the command line (`--decision accept --reason "..."` for the first two, `--decision release --reason "..."` for cloud-deployment) so the log opened on camera shows a decision, not `pending`; the committed `multi-agent-review.md` and `cloud-deployment-review.md` still say pending, so re-run and recommit them before the video.
4. A registered account on the local site and one on the deployed site, both logged out, so each login is shown live.
5. Garden **Backyard** (Melbourne, Australia) with area **North bed** and plantings **Basil ×6 (Sown)**, **Tomato (Roma) ×3 (Growing)**. Click **Sync this garden to the knowledge base** once.
6. Plant Health: plant name **Tomato in the back bed** with two or three earlier assessments. Click **Sync records to the knowledge base** once. One clear photo of a plant with yellowing leaves on the desktop.
7. Almanac opened once so the seed catalogue has loaded, then, while logged in, on **Reference tools** expand **Updated the catalogue?** and click **Refresh references** once so the RAG server has indexed the catalogue (otherwise "Ask with sources" answers "insufficient context").
8. Browser tabs ready: GitHub **Actions** filtered to each of `vgarden.yml`, `plant_almanac.yml`, `health.yml` and `cloud-deployment.yml` (one green run each, opened at the "Test the two assigned endpoint functions" step); the Azure portal resource group `rg-plantms-prod`; the deployed proxy URL from `docs/evidence/release2/cloud-deployment/latest.md`; `http://127.0.0.1:8003/dashboard`.
9. The deployed site must be on the **baseline** profile for the cloud shot: `curl <deployed URL>/vgarden/integrations` must report `"enabled": false` for `mcp`, `rag` and `multi_agent`. A bonus-profile run leaves them enabled. `gh workflow run cloud-deployment.yml -f service_min_replicas=1`, approved in `azure-production`, puts the baseline back in 6–10 minutes and keeps every service warm so the first click is instant; run it again without `-f` after recording to scale back to zero.
10. A one-line change staged so a commit can be shown running the pre-commit hooks.
11. Record the model waits in full, then cut them in editing. On CPU the garden workflow, the health assessment and the review modes can each take one to three minutes; with the models on a GPU a Planner, Worker, Reviewer run takes about 15 to 25 seconds and a chat answer 5 to 10 seconds.
12. If any container is recreated (for example after a compose change), restart the proxy too: nginx caches each backend's IP at startup and otherwise answers 502.
13. On the Windows/WSL laptop, `docker-compose.demo.yml` holds the recording settings and the rerun steps are in its header comment.

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

## 2:05 – Plant Almanac and the Multi-Agent Server (≈140 words)

`[Click "Almanac". Type "tomato" in the search box, open the Tomato card. Click "Edit", change one field, save.]`

**Amy**
> I own the Plant Almanac, the public plant, pest and disease catalogue, with CRUD for plant records. Its Release 1 reference tools are retained: an MCP catalogue search and a RAG "ask with sources" panel, both reached through the Almanac backend.

`[Click the floating "Ask the Almanac" button. Click the chip "Compare basil and zucchini". Cut the wait. Click "✓ Answer checked · View validation report →".]`

> AI-Mode is grounded in the catalogue, and each answer carries its Plan, Act, Observe, Adapt validation report.

`[Back in the chat, click the "Multi-Agent" tab. Ask "What should I plant this month?". Click "Run agents". Cut the wait. Show "Check the saved facts · N sources", then choose "Accept answer" and click "Save my review".]`

> I also built the shared Multi-Agent Server itself. The Planner decides what evidence is needed, the Worker retrieves it through the MCP server and drafts, and the Reviewer checks every claim against the cited records before the human decides. The same server serves all three features with per-source prompts, keeps every transition in its own store, and exports the workflow history and coordination audit logs. The Reviewer's comparison check was my fix for a draft that claimed facts the zucchini record never stated.

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

**Yunus**
> Every commit runs four local pre-commit hooks: Ruff security rules, detect-secrets, pip-audit, and the service's tests. A failing hook blocks the commit.

`[Open docs/evidence/release2/pre-commit-all-services.md — the PASS table.]`

> The report scans every tracked file of every service and goes in the technical report.

`[GitHub Actions: open the green run of "Virtual Garden (Yunus)", expand "Test the two assigned endpoint functions".]`

> After each push my workflow tests two endpoint functions, create garden and garden snapshot, and uploads the JUnit results as an artefact.

`[Open the green run of "Plant Almanac (Amy)", same step.]`

**Amy**
> Mine tests the catalogue search and the plant detail endpoints of the Almanac API.

`[Open the green run of "Plant Health (Guhan)", same step.]`

**Guhan**
> Mine tests create assessment and list assessments, then runs the remaining regression suite and the compose smoke test with the AI switched off.

## 5:20 – Cloud deployment: every feature in Azure (≈145 words)

`[Open the green "cloud-deployment.yml" run. Show the gate jobs, then the Bicep and deploy steps. Switch to the Azure resource group.]`

**Yunus**
> A green main triggers the cloud deployment workflow. After the CI gates pass, Bicep provisions the registry, Key Vault, network and six container apps, and the reusable deploy scripts push the same images we run locally, with PostgreSQL in place of SQLite.

`[Open the deployed URL. Log in, click "+ Add a garden", create "Cloud test", open it, add a planting. Scroll to the panels: "MCP off", "RAG off", "Multi-Agent off".]`

> The same UI and CRUD work in Azure. As the brief requires, AI-Mode, MCP, RAG and the Multi-Agent Server are disabled by default in the cloud, and the deploy scripts are reusable: the same script that GitHub Actions runs deploys from a laptop after an Azure login.

`[Still on the deployed site, click "Almanac". Type "tomato" in "Search plants or varieties…", open the Tomato card, click "Edit", change one field, click "Save changes". The card shows the new value.]`

**Amy**
> The Almanac catalogue and its CRUD run on PostgreSQL in Azure with the same templates; the chat and reference tools are switched off here, as the baseline requires.

`[Click "Plant Health". Choose "Other / new plant…", type "Cloud tomato", description "Lower leaves yellowing", click "Assess plant health". The record is saved at once; its summary starts "Not assessed." and names AI-Mode as off.]`

**Guhan**
> With AI-Mode off, Plant Health still saves the record, marked not assessed, so create, read, update and delete work without a model; "Generate report again" assesses it later wherever AI-Mode is on.

## 6:35 – Agentic-loop review modes (≈75 words)

`[Terminal: run the three review commands in turn. Open the review log for one, scroll to "Human decision".]`

**Amy**
> The shared agentic loop gained three Release 2 modes alongside the Release 1 MCP and RAG modes. Multi-Agent Review checks the workflow history and audit logs, Testing Review reads the pre-commit and CI evidence, and Cloud Deployment Review reads the deployment report and the baseline switches. Each one runs fixed checks first, drafts findings with a local model, has a second model review the draft, and ends in a human release decision written into the log.

## 7:15 – Close (≈40 words)

`[Return to the local landing page.]`

**Guhan**
> To recap: an integrated application running locally and in Azure, a Multi-Agent workflow through every feature's UI and the terminal, security scans on every commit, endpoint tests on every push, and reviews of our own release. Thanks for watching.

`[Hold for two seconds. End.]`

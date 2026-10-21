# Release 2 showcase video — plan and shot list (max 10 minutes)

The brief requires one group video, all three students on camera/voice, showing: the
Multi-Agent workflow through the frontend UI, the frontend UI in both the local and
the cloud deployment, pre-commit security scans, post-commit CI/CD endpoint testing,
and the agentic-loop review modes. Each student explains and defends their own
Release 2 contribution (criterion 10). Put the published URL in the report's last
section.

## Before recording

1. Start everything (see [`docs/evidence/release2/local-deployment/README.md`](../evidence/release2/local-deployment/README.md)):
   terminal 1 `docker compose up -d --build`, terminal 2 MCP server, terminal 3 RAG
   server, terminal 4 Multi-Agent Server (`MULTI_AGENT_HOST=0.0.0.0` on Linux/WSL).
   Keep the four terminals visible side by side for the "multiple terminals" shot.
2. Seed data: a few Plant Health assessments for one plant, one garden with plantings,
   the Almanac catalogue loaded. Sync the RAG knowledge base once.
3. Have the Azure proxy URL open in a second browser window, and the GitHub Actions
   page for the latest `health.yml`, `vgarden.yml`, `plant_almanac.yml` and
   `cloud-deployment.yml` runs.
4. Have a small, harmless code change staged so a `git commit` can be shown running the
   pre-commit hooks live (Ruff S, detect-secrets, pip-audit, feature tests).

## Shot list (target 9:30)

| # | Time | Who | What is on screen | What is said |
| --- | --- | --- | --- | --- |
| 1 | 0:00–0:40 | all | Title slide: team, feature allocation, Release 2 design-flow diagram (`docs/architecture/release2-design-flow.svg`) | What Release 1 was; what Release 2 adds (Multi-Agent Server, review modes, pre-commit, post-commit endpoint CI, local + cloud deployment) |
| 2 | 0:40–1:30 | Guhan | The four terminals (compose, MCP, RAG, Multi-Agent) and `http://localhost:3000` | Local deployment: containers vs the non-containerised shared servers; each `/integrations` endpoint shows MCP, RAG and Multi-Agent **on** |
| 3 | 1:30–3:00 | Guhan | Plant Health page: start an **Agent workflow** for a plant; stage badges while it runs; Planner steps, Worker answer with citations, Reviewer issues; *Request changes* → revised run; final *Accept* / *Partially accept*. Then `/dashboard` on :8003 and the audit download | Frontend UI → backend → Multi-Agent Server → Planner → Worker → Reviewer → human review → back to the page; evidence is only this plant's assessments; why the human decision is final |
| 4 | 3:00–4:00 | Yunus | A garden page: the same workflow on garden records; terminal run `scripts/test/multi-agent-vgarden.sh` | Private per-owner data stays in the backend; terminal path of the server |
| 5 | 4:00–4:45 | Amy | Almanac workflow (Worker retrieves through MCP); the server's Planner/Worker/Reviewer code and audit/metrics | How the shared server is built; workflow history and coordination audit files |
| 6 | 4:45–5:45 | Amy | `git commit` on a staged change: the four hooks run and pass; `.security-reports/` file; the pre-commit report pages | Pre-commit security testing: Ruff security rules, detect-secrets, pip-audit, feature tests; how findings are handled |
| 7 | 5:45–6:45 | each student 20 s | GitHub Actions: a successful push run of `plant_almanac.yml`, `vgarden.yml`, `health.yml`; open the test-evidence artifact (JUnit, logs, `run.json`) | Each names their two endpoint functions and what the tests check |
| 8 | 6:45–7:45 | Guhan | `cloud-deployment.yml` run: gates → deploy → environment approval; the Azure proxy URL in the browser: log in, Plant Health CRUD, `/integrations` reporting MCP/RAG/Multi-Agent **off** | Cloud deployment and the baseline rule; Bicep and scripts; the human release decision |
| 9 | 7:45–8:45 | Yunus | `tools/ai-loop/validate.py` in the three Release 2 review modes (Multi-Agent review, Testing Report review, Cloud Deployment Report review) and the generated review/validation logs | What each mode reviews and where its log lands |
| 10 | 8:45–9:30 | all | Contribution summary slide, repository URL, report sections | Each student: one sentence on what they would defend in Q&A |

## Recording notes

- Record at 1080p, one take per shot; stitch shots rather than one long take.
- Show URLs and terminal prompts clearly; zoom the terminal font to 14pt+.
- Where a model run takes minutes, cut to the finished state and say the elapsed time
  (the evidence logs record it).
- Upload unlisted (YouTube or OneDrive), test the link in a private window, and paste it
  into the report's "Showcase Video URL" section.

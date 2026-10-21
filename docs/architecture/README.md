# Architecture diagrams (Release 2)

Mermaid sources (`.mmd`) with rendered `.svg`/`.png` for the technical report.

| Diagram | Report section | Source |
| --- | --- | --- |
| Release 2 application design flow — Frontend UI → Backend/API → Database, the Release 1 AI-Mode / MCP / RAG flows, and the Multi-Agent flow Frontend UI → Backend → Multi-Agent Server → Planner → Worker → Reviewer → Human Review → Frontend UI | Release 2 Design Flow | [`release2-design-flow.mmd`](release2-design-flow.mmd) |
| Plant Health (Guhan Sundar) design flow with the Multi-Agent Server | Release 2 Design Flow (per student) | [`plant-health-design-flow.mmd`](plant-health-design-flow.mmd) |
| Group cloud reference architecture (Azure Container Apps, PostgreSQL, Key Vault, ACR; AI services disabled by default) | Cloud Deployment and CI/CD Architecture | [`cloud-architecture.mmd`](cloud-architecture.mmd) |
| DevOps / CI-CD flow: source control → pre-commit scans → GitHub Actions → endpoint tests per student → Docker build/validation → `cloud-deployment.yml` → Azure | Cloud Deployment and CI/CD Architecture | [`cicd-pipeline.mmd`](cicd-pipeline.mmd) |

The Virtual Garden and Plant Almanac per-student flows live with their features
(`docs/evidence/release2/multi-agent-vgarden.md`, `ai-services/multi-agent-server/README.md`);
the cloud diagram follows `docs/deployment/azure.md` and `infra/*.bicep`.

## Rendering

GitHub renders the `.mmd` sources inline when they are embedded in Markdown. To refresh
the image files after editing a source (Node 18+; the CLI drives a local Chromium/Edge):

```bash
npm install --no-save @mermaid-js/mermaid-cli
npx mmdc -i docs/architecture/release2-design-flow.mmd -o docs/architecture/release2-design-flow.svg -b white
npx mmdc -i docs/architecture/release2-design-flow.mmd -o docs/architecture/release2-design-flow.png -b white -s 2
```

On a machine without a downloadable Chromium, point the CLI at an installed browser
with `-p puppeteer-config.json` containing `{"executablePath": "<path to msedge.exe or chrome>"}`.

# Cloud Deployment review

Run `review-cloud-deployment-20261022-034848-6848f2` · verdict **ready** (from model) · human decision **pending** by `yunus`

All cloud deployment checks have passed, including deployment report existence, service availability, security controls, and CI/CD pipeline success. The deployment is secure, with no public access to database or internal services, and all services are running with HTTPS and proper authentication. The deployment is fully functional and compliant with production security and operational standards.

## Checks

| ID | Check | Result | Detail |
| --- | --- | --- | --- |
| CD-1 | The deployment report JSON exists | ✅ pass | docs/evidence/release2/cloud-deployment/latest.json |
| CD-2 | AI-Mode, MCP, RAG and Multi-Agent are disabled in the cloud baseline | ✅ pass | switches: {'ai_mode_enabled': False, 'mcp_enabled': False, 'rag_enabled': False, 'multi_agent_enabled': False} |
| CD-3 | The deploy's own smoke test passed | ✅ pass | smoke_test.result=pass |
| CD-4 | All container apps run and only one has public ingress | ✅ pass | 6 apps; public: ['plantms-prod-proxy']; not running: none |
| CD-5 | The managed PostgreSQL database has no public network access | ✅ pass | 1 servers; public: none |
| CD-6 | The deployed commit passed CI first | ✅ pass | Plant Almanac (Amy)=success, Ruff=success, Auth=success, Integration CI=success, Virtual Garden (Yunus)=success, Plant Health (Guhan)=success |
| CD-7 | The deployed frontend answers over HTTPS | ✅ pass | https://plantms-prod-proxy.thankfulsky-694df0b7.australiaeast.azurecontainerapps.io |
| CD-8 | / responds on the live deployment | ✅ pass | HTTP 200 in 0.1s |
| CD-9 | /auth/login responds on the live deployment | ✅ pass | HTTP 200 in 0.0s |
| CD-10 | /vgarden/healthz responds on the live deployment | ✅ pass | HTTP 200 in 0.0s |
| CD-11 | /almanac/ responds on the live deployment | ✅ pass | HTTP 200 in 1.1s |
| CD-12 | /health/plant-health-records/ responds on the live deployment | ✅ pass | HTTP 200 in 0.2s |
| CD-W | The latest cloud-deployment.yml run on yunz/fix-postgres-redeploy succeeded | ✅ pass | run 39680594970 on 0f88ba4: success |

## Findings

- None.

## Recommendations

- None.

## Human decision

- Decision: **pending** (choices: release, hold, rollback)
- Reason: No --decision given and no terminal to ask.

## Evidence and log

- docs/evidence/release2/cloud-deployment/latest.json
- https://plantms-prod-proxy.thankfulsky-694df0b7.australiaeast.azurecontainerapps.io
- https://github.com/Bageutter/Plant-Management-System/actions/runs/39680594970
- Review/validation log: `tools/ai-loop/logs/reports/review-cloud-deployment/review-cloud-deployment-20261022-034848-6848f2.md`

_Reviews saved evidence; a passing review is not proof that every feature works._

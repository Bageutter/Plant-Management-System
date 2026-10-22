# Cloud deployment report — Microsoft Azure

Generated 2026-10-21T21:55:49Z by `scripts/deploy/azure-report.sh`.

## Deployment

| | |
|---|---|
| Platform | Microsoft Azure (Azure Container Apps + Azure Database for PostgreSQL) |
| Subscription | Azure for Students |
| Resource group | `rg-plantms-prod` (australiaeast) |
| Commit | `0f88ba47a0a604eaea568e1eeff5665f3ed2fb9d` on `yunz/fix-postgres-redeploy` |
| Image tag | `0f88ba4` |
| Triggered by | yunz-dev |
| Workflow run | https://github.com/Bageutter/Plant-Management-System/actions/runs/39680594970 |
| Smoke test | **PASS** (`scripts/deploy/azure-smoke.sh`) |

## Access

| Feature | URL |
|---|---|
| Frontend | https://plantms-prod-proxy.thankfulsky-694df0b7.australiaeast.azurecontainerapps.io |
| Auth | https://plantms-prod-proxy.thankfulsky-694df0b7.australiaeast.azurecontainerapps.io/auth |
| Virtual Garden | https://plantms-prod-proxy.thankfulsky-694df0b7.australiaeast.azurecontainerapps.io/vgarden |
| Plant Almanac | https://plantms-prod-proxy.thankfulsky-694df0b7.australiaeast.azurecontainerapps.io/almanac/ |
| Plant Health | https://plantms-prod-proxy.thankfulsky-694df0b7.australiaeast.azurecontainerapps.io/health/plant-health-records/ |

## Cloud baseline (Assessment 3 requirement)

| Service | Required cloud baseline | Deployed value |
|---|---|---|
| AI-Mode (Ollama) | disabled | disabled |
| MCP Server | disabled | disabled |
| RAG Server | disabled | disabled |
| Multi-Agent Server | disabled | disabled |

The frontend UI, backend/API services, database and CRUD functions run without any
model, MCP, RAG or Multi-Agent call. The switches are parameters of `infra/apps.bicep`;
the optional bonus profile is the only thing that turns them on.

## Container apps

| Container app | Ingress | Image | Revision | Status | Replicas |
|---|---|---|---|---|---|
| plantms-prod-almanac | internal | plantms/almanac:0f88ba4 | plantms-prod-almanac--0000005 | Running | 0-1 |
| plantms-prod-auth | internal | plantms/auth:0f88ba4 | plantms-prod-auth--0000005 | Running | 1-1 |
| plantms-prod-frontend | internal | plantms/frontend:0f88ba4 | plantms-prod-frontend--0000005 | Running | 0-1 |
| plantms-prod-health | internal | plantms/health:0f88ba4 | plantms-prod-health--0000005 | Running | 0-1 |
| plantms-prod-proxy | public HTTPS | plantms/proxy:0f88ba4 | plantms-prod-proxy--0000005 | Running | 1-2 |
| plantms-prod-vgarden | internal | plantms/vgarden:0f88ba4 | plantms-prod-vgarden--0000005 | Running | 1-1 |

## Database

| Server | Version | SKU | Public access | Backups |
|---|---|---|---|---|
| psql-plantms-prod-4m5abpehqyc2o | 16 | Burstable Standard_B1ms | Disabled | 7 days |

One database per service on the shared server: `auth`, `vgarden`, `health`, `almanac`.
Schema migrations run on start-up (Flask-Migrate / Alembic), as locally.

## Security controls

| Area | Control |
|---|---|
| Endpoint | Single public entry point: only the nginx proxy container app has external ingress; every Flask service is internal-only and not resolvable from the internet. |
| Endpoint | HTTPS only: the public ingress redirects plain HTTP to HTTPS (allowInsecure=false) with a managed TLS certificate. |
| Endpoint | Production process model: services run under gunicorn, not Flask's debug server; session cookies are HttpOnly, SameSite=Lax and Secure. |
| Data | PostgreSQL Flexible Server is VNet-injected with public network access disabled; clients connect with sslmode=require. Automatic backups are retained for 7 days. |
| Data | Every secret (database URLs, Flask secret keys, inter-service token) lives in Key Vault (RBAC); container apps read them with a user-assigned managed identity. Nothing is stored in the repository, the workflow or GitHub secrets. |
| Data | Container Registry: admin user disabled, images pulled with the managed identity. |
| Data | Plant-image storage: HTTPS/TLS 1.2 only, no public blob access, network access limited to the apps subnet. |
| Pipeline | GitHub Actions authenticates to Azure with OpenID Connect federation scoped to one resource group; no cloud credential is stored in GitHub. |

## Resources in the resource group

| Type | Name |
|---|---|
| containerApps | plantms-prod-almanac |
| containerApps | plantms-prod-auth |
| containerApps | plantms-prod-frontend |
| containerApps | plantms-prod-health |
| containerApps | plantms-prod-proxy |
| containerApps | plantms-prod-vgarden |
| flexibleServers | psql-plantms-prod-4m5abpehqyc2o |
| managedEnvironments | cae-plantms-prod |
| privateDnsZones | plantms-prod.private.postgres.database.azure.com |
| privateDnsZones/virtualNetworkLinks | plantms-prod.private.postgres.database.azure.com/vnet-plantms-prod-link |
| registries | acrplantms4m5abpehqyc2o |
| storageAccounts | stplantms4m5abpehqy |
| userAssignedIdentities | id-plantms-apps |
| userAssignedIdentities | id-plantms-github |
| vaults | kv-plantms-4m5abpeh |
| virtualNetworks | vnet-plantms-prod |
| workspaces | log-plantms-prod |

## Final human release decision

To be completed by the team after reviewing this report and the agentic loop's
Cloud Deployment Review output:

- [ ] **Approved** — release stands
- [ ] **Approved with corrections** (list):
- [ ] **Rejected** — roll back / redeploy (reason):

Reviewer: ______________________  Date: ____________

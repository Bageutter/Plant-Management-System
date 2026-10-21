# infra — Azure infrastructure as code (Bicep)

| File | Deploys | Run by |
|---|---|---|
| `main.bicep` | the platform: VNet, PostgreSQL Flexible Server (private, one database per service), Key Vault + secrets, Container Registry, storage + file share, Log Analytics, Container Apps environment | `scripts/deploy/azure-platform.sh` |
| `apps.bicep` | the six container apps (proxy, frontend, auth, vgarden, almanac, health) with the cloud baseline switches | `scripts/deploy/azure-apps.sh` |
| `modules/container-app.bicep` | one container app (identity, registry, Key Vault secret refs, probes, scale) | `apps.bicep` |

Two deployments because the apps need images that are pushed to the registry
`main.bicep` creates. Both are idempotent; `scripts/deploy/azure-deploy.sh` runs
them in order with the image build in between. Identities and role assignments are
created once by `scripts/deploy/azure-bootstrap.sh`, not here, so the CI identity
never needs permission to grant roles.

Validate locally without deploying:

```bash
az bicep build --file infra/main.bicep --stdout > /dev/null && az bicep build --file infra/apps.bicep --stdout > /dev/null
az deployment group what-if -g rg-plantms-prod -f infra/apps.bicep -p environmentName=... acrLoginServer=... keyVaultName=... imageTag=...
```

Full walkthrough: [docs/deployment/azure.md](../docs/deployment/azure.md).

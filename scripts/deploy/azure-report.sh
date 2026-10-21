#!/usr/bin/env bash
# Write the cloud deployment report: what was deployed, where, from which commit,
# with which switches, and whether the smoke test passed.
#
#   bash scripts/deploy/azure-report.sh [pass|fail]
#
# Produces, in $REPORT_DIR (docs/evidence/release2/cloud-deployment by default):
#   cloud-deployment-<timestamp>.json   machine-readable grounding for the shared
#                                       agentic loop's Cloud Deployment Review mode
#   cloud-deployment-<timestamp>.md     the human-readable report for the technical
#                                       report, ending with the release decision
#   latest.json / latest.md             copies of the newest run
# In GitHub Actions the markdown is also appended to the job summary.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/azure-config.sh"
require_az_login

smoke_result=${1:-unknown}
python=$(command -v python3 || command -v python)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

step "Collecting deployment facts"
az deployment group show -g "$AZURE_RESOURCE_GROUP" -n "$PLATFORM_DEPLOYMENT" \
  --query "properties.outputs" -o json >"$work/platform.json"
az deployment group show -g "$AZURE_RESOURCE_GROUP" -n "$APPS_DEPLOYMENT" \
  --query "properties.outputs" -o json >"$work/apps.json"
az containerapp list -g "$AZURE_RESOURCE_GROUP" \
  --query "[].{name:name, external:properties.configuration.ingress.external, allowInsecure:properties.configuration.ingress.allowInsecure, fqdn:properties.configuration.ingress.fqdn, image:properties.template.containers[0].image, revision:properties.latestRevisionName, status:properties.runningStatus, minReplicas:properties.template.scale.minReplicas, maxReplicas:properties.template.scale.maxReplicas, secrets:length(properties.configuration.secrets || \`[]\`)}" \
  -o json >"$work/containerapps.json"
az postgres flexible-server list -g "$AZURE_RESOURCE_GROUP" \
  --query "[].{name:name, version:version, sku:sku.name, tier:sku.tier, publicNetworkAccess:network.publicNetworkAccess, fqdn:fullyQualifiedDomainName, backupRetentionDays:backup.backupRetentionDays}" \
  -o json >"$work/postgres.json"
az keyvault list -g "$AZURE_RESOURCE_GROUP" \
  --query "[].{name:name, rbac:properties.enableRbacAuthorization, softDelete:properties.enableSoftDelete}" \
  -o json >"$work/keyvault.json"
az storage account list -g "$AZURE_RESOURCE_GROUP" \
  --query "[].{name:name, minimumTlsVersion:minimumTlsVersion, httpsOnly:enableHttpsTrafficOnly, blobPublicAccess:allowBlobPublicAccess, networkDefaultAction:networkRuleSet.defaultAction}" \
  -o json >"$work/storage.json"
az resource list -g "$AZURE_RESOURCE_GROUP" --query "[].{name:name, type:type}" -o json >"$work/resources.json"

cat >"$work/context.json" <<JSON
{
  "generated_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "platform": "Microsoft Azure",
  "subscription": "$(azq account show --query name)",
  "resource_group": "$AZURE_RESOURCE_GROUP",
  "location": "$AZURE_LOCATION",
  "image_tag": "$IMAGE_TAG",
  "commit": "$(git -C "$ROOT" rev-parse HEAD 2>/dev/null || echo unknown)",
  "branch": "${GITHUB_REF_NAME:-$(git -C "$ROOT" branch --show-current 2>/dev/null || echo unknown)}",
  "actor": "${GITHUB_ACTOR:-$(git -C "$ROOT" config user.name 2>/dev/null || echo local)}",
  "workflow_run_url": "${GITHUB_SERVER_URL:-}${GITHUB_REPOSITORY:+/$GITHUB_REPOSITORY}${GITHUB_RUN_ID:+/actions/runs/$GITHUB_RUN_ID}",
  "smoke_result": "$smoke_result",
  "cloud_baseline": {
    "ai_mode_enabled": $CLOUD_AI_ENABLED,
    "mcp_enabled": $MCP_ENABLED,
    "rag_enabled": $RAG_ENABLED,
    "multi_agent_enabled": $MULTI_AGENT_ENABLED
  }
}
JSON

mkdir -p "$REPORT_DIR"
"$python" -I "$ROOT/scripts/deploy/azure_report.py" "$work" "$REPORT_DIR"

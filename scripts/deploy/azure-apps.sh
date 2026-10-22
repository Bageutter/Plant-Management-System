#!/usr/bin/env bash
# Roll out the container apps: infra/apps.bicep with the images tagged IMAGE_TAG.
# Prints the public URL and, inside GitHub Actions, exposes it as the step output
# `app_url` (the deploy job's environment URL).
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/azure-config.sh"
require_az_login

step "Apps deployment '$APPS_DEPLOYMENT' (image tag $IMAGE_TAG)"
echo "    profile: $DEPLOY_PROFILE (AI apps deployed: $AI_SERVICES_DEPLOYED, models: $CLOUD_TEXT_MODEL / $CLOUD_VISION_MODEL)"
echo "    cloud baseline: ai=$CLOUD_AI_ENABLED mcp=$MCP_ENABLED rag=$RAG_ENABLED multi_agent=$MULTI_AGENT_ENABLED"
echo "    replicas: proxy>=$PROXY_MIN_REPLICAS services>=$SERVICE_MIN_REPLICAS"

az deployment group create \
  --resource-group "$AZURE_RESOURCE_GROUP" \
  --name "$APPS_DEPLOYMENT" \
  --template-file "$ROOT/infra/apps.bicep" \
  --parameters \
    baseName="$AZURE_BASE_NAME" \
    stage="$AZURE_STAGE" \
    location="$AZURE_LOCATION" \
    appsIdentityName="$APPS_IDENTITY" \
    environmentName="$(platform_output environmentName)" \
    acrLoginServer="$(platform_output acrLoginServer)" \
    keyVaultName="$(platform_output keyVaultName)" \
    almanacStorageName="$(platform_output almanacStorageName)" \
    imageTag="$IMAGE_TAG" \
    proxyMinReplicas="$PROXY_MIN_REPLICAS" \
    serviceMinReplicas="$SERVICE_MIN_REPLICAS" \
    dependencyMinReplicas="${DEPENDENCY_MIN_REPLICAS:-1}" \
    aiEnabled="$CLOUD_AI_ENABLED" \
    mcpEnabled="$MCP_ENABLED" \
    ragEnabled="$RAG_ENABLED" \
    multiAgentEnabled="$MULTI_AGENT_ENABLED" \
    aiServicesDeployed="$AI_SERVICES_DEPLOYED" \
    ollamaStorageName="$(platform_output ollamaStorageName)" \
    ollamaImage="$(platform_output acrLoginServer)/ollama/ollama:${OLLAMA_SOURCE_IMAGE##*:}" \
    textModel="$CLOUD_TEXT_MODEL" \
    visionModel="$CLOUD_VISION_MODEL" \
    aiMinReplicas="$AI_MIN_REPLICAS" \
    ${OLLAMA_URL:+ollamaUrl="$OLLAMA_URL"} \
    ${MCP_SERVER_URL:+mcpServerUrl="$MCP_SERVER_URL"} \
    ${RAG_SERVER_URL:+ragServerUrl="$RAG_SERVER_URL"} \
    ${MULTI_AGENT_URL:+multiAgentUrl="$MULTI_AGENT_URL"} \
  --output none

# Back on the baseline after a bonus deployment: the AI apps are no longer used by
# any feature (Bicep leaves existing apps in place), so make sure none stays warm
# and keeps billing. They wake again only if the bonus profile is redeployed.
if [[ $AI_SERVICES_DEPLOYED != true ]]; then
  for app in ollama mcp rag agents; do
    name="$AZURE_BASE_NAME-$AZURE_STAGE-$app"
    if az containerapp show -g "$AZURE_RESOURCE_GROUP" -n "$name" -o none 2>/dev/null; then
      step "Baseline: scaling the unused bonus app $name to zero"
      az containerapp update -g "$AZURE_RESOURCE_GROUP" -n "$name" --min-replicas 0 -o none
    fi
  done
fi

app_url=$(apps_output appUrl)
step "Deployed: $app_url"
az containerapp list -g "$AZURE_RESOURCE_GROUP" \
  --query "[].{app:name, external:properties.configuration.ingress.external, fqdn:properties.configuration.ingress.fqdn, revision:properties.latestRevisionName, status:properties.runningStatus}" \
  -o table

if [[ -n ${GITHUB_OUTPUT:-} ]]; then
  echo "app_url=$app_url" >>"$GITHUB_OUTPUT"
fi

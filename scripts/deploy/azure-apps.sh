#!/usr/bin/env bash
# Roll out the container apps: infra/apps.bicep with the images tagged IMAGE_TAG.
# Prints the public URL and, inside GitHub Actions, exposes it as the step output
# `app_url` (the deploy job's environment URL).
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/azure-config.sh"
require_az_login

step "Apps deployment '$APPS_DEPLOYMENT' (image tag $IMAGE_TAG)"
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
    aiEnabled="$CLOUD_AI_ENABLED" \
    mcpEnabled="$MCP_ENABLED" \
    ragEnabled="$RAG_ENABLED" \
    multiAgentEnabled="$MULTI_AGENT_ENABLED" \
    ${OLLAMA_URL:+ollamaUrl="$OLLAMA_URL"} \
    ${MCP_SERVER_URL:+mcpServerUrl="$MCP_SERVER_URL"} \
    ${RAG_SERVER_URL:+ragServerUrl="$RAG_SERVER_URL"} \
    ${MULTI_AGENT_URL:+multiAgentUrl="$MULTI_AGENT_URL"} \
  --output none

app_url=$(apps_output appUrl)
step "Deployed: $app_url"
az containerapp list -g "$AZURE_RESOURCE_GROUP" \
  --query "[].{app:name, external:properties.configuration.ingress.external, fqdn:properties.configuration.ingress.fqdn, revision:properties.latestRevisionName, status:properties.runningStatus}" \
  -o table

if [[ -n ${GITHUB_OUTPUT:-} ]]; then
  echo "app_url=$app_url" >>"$GITHUB_OUTPUT"
fi

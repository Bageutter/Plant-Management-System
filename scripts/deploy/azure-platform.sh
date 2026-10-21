#!/usr/bin/env bash
# Deploy (or update) the platform: infra/main.bicep.
#
# Secrets are generated exactly once. On the first run they are created here and
# stored in Key Vault by the template; on every later run they are read back from
# Key Vault, so re-deploying never rotates a password or signs users out. Any of
# them can be overridden with the matching environment variable, e.g. to rotate:
#   POSTGRES_ADMIN_PASSWORD=... bash scripts/deploy/azure-platform.sh
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/azure-config.sh"
require_az_login

step "Platform deployment '$PLATFORM_DEPLOYMENT' into $AZURE_RESOURCE_GROUP"

existing_vault=$(azq keyvault list -g "$AZURE_RESOURCE_GROUP" \
  --query "[?starts_with(name, 'kv-${AZURE_BASE_NAME}-')].name | [0]" 2>/dev/null || true)
[[ -n $existing_vault ]] && echo "    reusing secrets from Key Vault $existing_vault"

secret_value() { # secret-name  env-override-name  generator
  local name=$1 override=${!2:-} value=""
  if [[ -n $override ]]; then
    value=$override
  elif [[ -n $existing_vault ]]; then
    value=$(azq keyvault secret show --vault-name "$existing_vault" -n "$name" --query value 2>/dev/null || true)
  fi
  if [[ -z $value ]]; then
    value=$($3)
    echo "    generated new value for $name" >&2
  fi
  # Keep it out of the Actions log even if something echoes it later.
  [[ -n ${GITHUB_ACTIONS:-} ]] && echo "::add-mask::$value"
  printf '%s' "$value"
}
random_key() { openssl rand -hex 32; }
# PostgreSQL wants 8-128 chars from at least three character classes.
random_password() { printf 'Pg%sA9' "$(openssl rand -hex 20)"; }

postgres_password=$(secret_value postgres-admin-password POSTGRES_ADMIN_PASSWORD random_password)
auth_secret=$(secret_value auth-secret-key AUTH_SECRET_KEY random_key)
vgarden_secret=$(secret_value vgarden-secret-key VGARDEN_SECRET_KEY random_key)
almanac_secret=$(secret_value almanac-secret-key ALMANAC_SECRET_KEY random_key)
inter_service_secret=$(secret_value inter-service-secret INTER_SERVICE_SECRET random_key)

# Secure parameters travel in a private temp file, never on the command line.
params=$(mktemp)
chmod 600 "$params"
trap 'rm -f "$params"' EXIT
cat >"$params" <<JSON
{
  "\$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
  "contentVersion": "1.0.0.0",
  "parameters": {
    "baseName": { "value": "$AZURE_BASE_NAME" },
    "stage": { "value": "$AZURE_STAGE" },
    "location": { "value": "$AZURE_LOCATION" },
    "appsIdentityName": { "value": "$APPS_IDENTITY" },
    "storageRestrictToVnet": { "value": ${STORAGE_RESTRICT_TO_VNET:-true} },
    "postgresAdminPassword": { "value": "$postgres_password" },
    "authSecretKey": { "value": "$auth_secret" },
    "vgardenSecretKey": { "value": "$vgarden_secret" },
    "almanacSecretKey": { "value": "$almanac_secret" },
    "interServiceSecret": { "value": "$inter_service_secret" }
  }
}
JSON

az deployment group create \
  --resource-group "$AZURE_RESOURCE_GROUP" \
  --name "$PLATFORM_DEPLOYMENT" \
  --template-file "$ROOT/infra/main.bicep" \
  --parameters "@$params" \
  --output none

step "Platform outputs"
az deployment group show -g "$AZURE_RESOURCE_GROUP" -n "$PLATFORM_DEPLOYMENT" \
  --query "properties.outputs" -o table

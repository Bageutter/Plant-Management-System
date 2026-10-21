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
stored_names=""
if [[ -n $existing_vault ]]; then
  echo "    reusing secrets from Key Vault $existing_vault"
  # Which secrets exist decides "generate" vs "fail": a secret that exists but cannot
  # be read must stop the deploy, never be silently replaced by a new value.
  stored_names=$(azq keyvault secret list --vault-name "$existing_vault" --query "[].name") || {
    echo "Cannot list the secrets in $existing_vault (needs Key Vault Secrets Officer/User)." >&2
    exit 1
  }
fi
stored() { grep -qx "$1" <<<"$stored_names"; }

secret_value() { # secret-name  env-override-name  generator
  local name=$1 override=${!2:-} value=""
  if [[ -n $override ]]; then
    value=$override
  elif stored "$name"; then
    value=$(azq keyvault secret show --vault-name "$existing_vault" -n "$name" --query value) || {
      echo "Cannot read $name from $existing_vault; refusing to replace it with a new value." >&2
      return 1
    }
  fi
  if [[ -z $value ]]; then
    value=$($3)
    echo "    generated new value for $name" >&2
  fi
  # Only the value goes to stdout: callers capture it with $(...). (The Actions
  # "::add-mask::" line used to be printed here too, so it was captured into the
  # secret itself and every CI deploy wrote a new, longer value: the database
  # password then no longer matched the server.) Masking happens in mask() below.
  printf '%s' "$value"
}
mask() { # keep a value out of the GitHub Actions log; must not run inside $(...)
  [[ -n ${GITHUB_ACTIONS:-} ]] && printf '::add-mask::%s\n' "$1"
  return 0
}
random_key() { openssl rand -hex 32; }
# PostgreSQL wants 8-128 chars from at least three character classes.
random_password() { printf 'Pg%sA9' "$(openssl rand -hex 20)"; }

postgres_password=$(secret_value postgres-admin-password POSTGRES_ADMIN_PASSWORD random_password)
auth_secret=$(secret_value auth-secret-key AUTH_SECRET_KEY random_key)
vgarden_secret=$(secret_value vgarden-secret-key VGARDEN_SECRET_KEY random_key)
almanac_secret=$(secret_value almanac-secret-key ALMANAC_SECRET_KEY random_key)
inter_service_secret=$(secret_value inter-service-secret INTER_SERVICE_SECRET random_key)
for value in "$postgres_password" "$auth_secret" "$vgarden_secret" "$almanac_secret" "$inter_service_secret"; do
  mask "$value"
done

# Create the PostgreSQL server only on the first run; afterwards reference it (see
# deployPostgres in infra/main.bicep). FORCE_POSTGRES=true re-sends its definition.
deploy_postgres=true
if [[ ${FORCE_POSTGRES:-false} != true ]] && [[ -n $(azq postgres flexible-server list -g "$AZURE_RESOURCE_GROUP" \
    --query "[?starts_with(name, 'psql-${AZURE_BASE_NAME}-${AZURE_STAGE}-')].name | [0]" 2>/dev/null || true) ]]; then
  deploy_postgres=false
  echo "    PostgreSQL server exists: referencing it, not redeploying it"
  # The template no longer re-sends the server, so a password that differs from the
  # one in Key Vault (a POSTGRES_ADMIN_PASSWORD rotation, or a first secret) must be
  # set on the server here, or every DATABASE_URL would stop matching it.
  current=""
  stored postgres-admin-password && current=$(azq keyvault secret show --vault-name "$existing_vault" \
    -n postgres-admin-password --query value)
  if [[ $postgres_password != "$current" ]]; then
    server=$(azq postgres flexible-server list -g "$AZURE_RESOURCE_GROUP" \
      --query "[?starts_with(name, 'psql-${AZURE_BASE_NAME}-${AZURE_STAGE}-')].name | [0]")
    echo "    setting the new administrator password on $server"
    az postgres flexible-server update -g "$AZURE_RESOURCE_GROUP" -n "$server" \
      --admin-password "$postgres_password" --output none
  fi
  unset current
fi

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
    "deployPostgres": { "value": $deploy_postgres },
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

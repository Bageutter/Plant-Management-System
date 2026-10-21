#!/usr/bin/env bash
# One-time Azure + GitHub setup for the cloud deployment. Run it ONCE, by a human
# who is Owner of the target subscription. After this, every deployment runs from
# GitHub Actions (.github/workflows/cloud-deployment.yml) as the identity created
# here, through OIDC federation: no cloud credential is ever stored in GitHub.
#
#   AZURE_SUBSCRIPTION_ID=<id> bash scripts/deploy/azure-bootstrap.sh
#
# What it does (idempotent, safe to re-run):
#   1. registers the resource providers the Bicep templates use
#   2. creates the resource group
#   3. creates two user-assigned managed identities
#        id-<base>-apps    the container apps (AcrPull + Key Vault Secrets User)
#        id-<base>-github  GitHub Actions (Contributor + Key Vault Secrets Officer,
#                          scoped to the resource group only)
#   4. federates id-<base>-github with this repository's main branch and the
#      GitHub environment used by the deploy job
#   5. writes AZURE_CLIENT_ID / AZURE_TENANT_ID / AZURE_SUBSCRIPTION_ID to the
#      repository as GitHub Actions secrets (needs repo admin; otherwise it prints
#      them for you to paste in Settings -> Secrets and variables -> Actions)
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/azure-config.sh"

: "${AZURE_SUBSCRIPTION_ID:?Set AZURE_SUBSCRIPTION_ID (see: az account list -o table)}"
require_az_login
az account set --subscription "$AZURE_SUBSCRIPTION_ID"
tenant_id=$(azq account show --query tenantId)
subscription_name=$(azq account show --query name)

echo "Subscription : $subscription_name ($AZURE_SUBSCRIPTION_ID)"
echo "Resource grp : $AZURE_RESOURCE_GROUP ($AZURE_LOCATION)"
echo "Repository   : $GITHUB_REPOSITORY (environment: $GITHUB_ENVIRONMENT)"

step "Registering resource providers"
providers=(Microsoft.App Microsoft.ContainerRegistry Microsoft.DBforPostgreSQL Microsoft.KeyVault
  Microsoft.ManagedIdentity Microsoft.Network Microsoft.OperationalInsights Microsoft.Storage)
for ns in "${providers[@]}"; do
  az provider register --namespace "$ns" --only-show-errors -o none
done
for ns in "${providers[@]}"; do
  until [[ $(azq provider show -n "$ns" --query registrationState) == Registered ]]; do
    echo "    waiting for $ns ..."
    sleep 10
  done
  echo "    $ns registered"
done

step "Resource group"
az group create -n "$AZURE_RESOURCE_GROUP" -l "$AZURE_LOCATION" \
  --tags project=plant-management-system stage="$AZURE_STAGE" managedBy=bicep -o none
rg_id=$(azq group show -n "$AZURE_RESOURCE_GROUP" --query id)

step "Managed identities"
az identity create -g "$AZURE_RESOURCE_GROUP" -n "$APPS_IDENTITY" -l "$AZURE_LOCATION" -o none
az identity create -g "$AZURE_RESOURCE_GROUP" -n "$GITHUB_IDENTITY" -l "$AZURE_LOCATION" -o none
apps_principal=$(azq identity show -g "$AZURE_RESOURCE_GROUP" -n "$APPS_IDENTITY" --query principalId)
github_principal=$(azq identity show -g "$AZURE_RESOURCE_GROUP" -n "$GITHUB_IDENTITY" --query principalId)
github_client_id=$(azq identity show -g "$AZURE_RESOURCE_GROUP" -n "$GITHUB_IDENTITY" --query clientId)

step "Role assignments (resource-group scope)"
assign() { # principal-object-id  principal-type  role
  local attempt
  for attempt in 1 2 3 4 5 6; do
    if az role assignment create --assignee-object-id "$1" --assignee-principal-type "$2" \
      --role "$3" --scope "$rg_id" -o none 2>/dev/null; then
      echo "    $3 -> $2 $1"
      return 0
    fi
    # A brand-new identity can take a little while to replicate in Entra ID.
    sleep 10
  done
  echo "could not assign '$3' to $1" >&2
  return 1
}
assign "$apps_principal" ServicePrincipal "AcrPull"
assign "$apps_principal" ServicePrincipal "Key Vault Secrets User"
assign "$github_principal" ServicePrincipal "Contributor"
assign "$github_principal" ServicePrincipal "Key Vault Secrets Officer"
# Let the person running this seed/read secrets with azure-platform.sh locally too.
if me=$(azq ad signed-in-user show --query id 2>/dev/null) && [[ -n $me ]]; then
  assign "$me" User "Key Vault Secrets Officer"
else
  echo "    (could not resolve your own user id; grant yourself 'Key Vault Secrets Officer' on the resource group if you want to run azure-platform.sh locally)"
fi

step "GitHub OIDC federation for $GITHUB_IDENTITY"
federate() { # credential-name  subject
  if az identity federated-credential show --identity-name "$GITHUB_IDENTITY" -g "$AZURE_RESOURCE_GROUP" -n "$1" -o none 2>/dev/null; then
    echo "    $1 exists ($2)"
  else
    az identity federated-credential create --identity-name "$GITHUB_IDENTITY" -g "$AZURE_RESOURCE_GROUP" -n "$1" \
      --issuer https://token.actions.githubusercontent.com --subject "$2" --audiences api://AzureADTokenExchange -o none
    echo "    $1 created ($2)"
  fi
}
federate github-main "repo:${GITHUB_REPOSITORY}:ref:refs/heads/main"
federate "github-env-${GITHUB_ENVIRONMENT}" "repo:${GITHUB_REPOSITORY}:environment:${GITHUB_ENVIRONMENT}"
# Repositories that use GitHub's immutable OIDC subject send
# "repo:<owner>@<owner id>/<repo>@<repo id>:..." instead (AADSTS700213 otherwise),
# so register that form too. The ids come from the public repository API.
repo_ids=${GITHUB_REPOSITORY_IDS:-$(curl -fsS "https://api.github.com/repos/${GITHUB_REPOSITORY}" 2>/dev/null \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print("%s@%s/%s@%s" % (d["owner"]["login"], d["owner"]["id"], d["name"], d["id"]))' 2>/dev/null || true)}
if [[ -n $repo_ids ]]; then
  federate github-main-ids "repo:${repo_ids}:ref:refs/heads/main"
  federate "github-env-${GITHUB_ENVIRONMENT}-ids" "repo:${repo_ids}:environment:${GITHUB_ENVIRONMENT}"
else
  echo "    (could not read the repository ids; set GITHUB_REPOSITORY_IDS=owner@id/repo@id if the deploy fails with AADSTS700213)"
fi

step "GitHub Actions secrets and variables"
set_secret() {
  if command -v gh >/dev/null && gh secret set "$1" --repo "$GITHUB_REPOSITORY" --body "$2" 2>/dev/null; then
    echo "    secret $1 set"
  else
    echo "    could not set secret $1 (needs repo admin). Add it by hand:  $1 = $2"
  fi
}
set_variable() {
  if command -v gh >/dev/null && gh variable set "$1" --repo "$GITHUB_REPOSITORY" --body "$2" 2>/dev/null; then
    echo "    variable $1 set"
  else
    echo "    could not set variable $1 (needs repo admin). Add it by hand:  $1 = $2"
  fi
}
set_secret AZURE_CLIENT_ID "$github_client_id"
set_secret AZURE_TENANT_ID "$tenant_id"
set_secret AZURE_SUBSCRIPTION_ID "$AZURE_SUBSCRIPTION_ID"
set_variable AZURE_RESOURCE_GROUP "$AZURE_RESOURCE_GROUP"
set_variable AZURE_LOCATION "$AZURE_LOCATION"
set_variable AZURE_BASE_NAME "$AZURE_BASE_NAME"
set_variable AZURE_STAGE "$AZURE_STAGE"

cat <<SUMMARY

Bootstrap complete.

  AZURE_CLIENT_ID       $github_client_id   (identity $GITHUB_IDENTITY; not a secret, but stored as one)
  AZURE_TENANT_ID       $tenant_id
  AZURE_SUBSCRIPTION_ID $AZURE_SUBSCRIPTION_ID

Next:
  * In GitHub: Settings -> Environments -> "$GITHUB_ENVIRONMENT": add yourselves as
    required reviewers. That approval is the human release decision for each deploy.
  * First deployment: Actions -> "Cloud deployment (Azure)" -> Run workflow, or locally
        bash scripts/deploy/azure-deploy.sh
    (role assignments can take a few minutes to propagate; retry if the first run
    is denied).
SUMMARY

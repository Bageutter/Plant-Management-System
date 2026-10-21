#!/usr/bin/env bash
# Delete everything the deployment created (the whole resource group), so the
# subscription stops being billed. The bootstrap identities live in the same
# group and go with it; re-run azure-bootstrap.sh before deploying again.
#
#   bash scripts/deploy/azure-teardown.sh            # asks for confirmation
#   CONFIRM=yes bash scripts/deploy/azure-teardown.sh
#
# Key Vault is soft-deleted for 7 days; the script purges it so the same name can
# be re-created immediately (set PURGE_KEY_VAULT=false to keep the soft-deleted copy).
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/azure-config.sh"
require_az_login

if [[ ${CONFIRM:-} != yes ]]; then
  read -r -p "Delete resource group '$AZURE_RESOURCE_GROUP' and everything in it? [yes/NO] " answer
  [[ $answer == yes ]] || { echo "aborted"; exit 1; }
fi

vaults=$(azq keyvault list -g "$AZURE_RESOURCE_GROUP" --query "[].name" 2>/dev/null || true)

step "Deleting $AZURE_RESOURCE_GROUP"
az group delete -n "$AZURE_RESOURCE_GROUP" --yes

if [[ ${PURGE_KEY_VAULT:-true} == true ]]; then
  for vault in $vaults; do
    step "Purging soft-deleted Key Vault $vault"
    az keyvault purge --name "$vault" -l "$AZURE_LOCATION" -o none || true
  done
fi
echo "done"

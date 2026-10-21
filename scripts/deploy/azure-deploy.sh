#!/usr/bin/env bash
# The whole cloud deployment, in order. This is what cloud-deployment.yml runs
# after the CI gates pass, and what a developer runs by hand:
#
#   az login            # once
#   bash scripts/deploy/azure-deploy.sh
#
#   1. azure-platform.sh     infra/main.bicep  (network, PostgreSQL, Key Vault, ACR, ...)
#   2. azure-build-push.sh   six images -> registry, tagged with the commit SHA
#   3. azure-apps.sh         infra/apps.bicep  (the six container apps)
#   4. azure-smoke.sh        end-to-end checks through the public HTTPS endpoint
#   5. azure-report.sh       deployment report + JSON grounding (always written)
#
# Prerequisite (once per subscription): azure-bootstrap.sh.
set -euo pipefail
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
source "$here/azure-config.sh"
require_az_login

bash "$here/azure-platform.sh"
bash "$here/azure-build-push.sh"
bash "$here/azure-apps.sh"

smoke=pass
if ! bash "$here/azure-smoke.sh"; then
  smoke=fail
fi
bash "$here/azure-report.sh" "$smoke"

if [[ $smoke == fail ]]; then
  echo "Deployment rolled out but the smoke test failed; see the report above." >&2
  exit 1
fi
echo "Deployment complete: $(apps_output appUrl)"

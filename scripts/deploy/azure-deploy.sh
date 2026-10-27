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
crud=pass
if [[ $DEPLOY_PROFILE == baseline && $smoke == pass ]]; then
  mkdir -p "$REPORT_DIR"
  if ! GITHUB_SHA=$(git -C "$ROOT" rev-parse HEAD) python3 "$here/azure-e2e.py" "$(apps_output appUrl)" \
    --json-out "$REPORT_DIR/e2e-crud.json" | tee "$REPORT_DIR/e2e-crud.txt"; then
    crud=fail
  fi
fi
bash "$here/azure-report.sh" "$smoke"

if [[ $smoke == fail || $crud == fail ]]; then
  echo "Deployment rolled out but validation failed (smoke=$smoke, CRUD=$crud); see the report above." >&2
  exit 1
fi
echo "Deployment complete: $(apps_output appUrl)"

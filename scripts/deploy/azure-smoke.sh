#!/usr/bin/env bash
# Smoke-check the deployed application through its public HTTPS entry point.
#
#   bash scripts/deploy/azure-smoke.sh                       # URL from the apps deployment
#   bash scripts/deploy/azure-smoke.sh https://plantms-prod-proxy.<domain>
#
# Proves, for the cloud deployment report:
#   * every feature answers through the proxy (frontend, auth, vgarden, almanac, health)
#   * CRUD APIs work without any model call (the shared scripts/test smoke scripts)
#   * the integrations report exactly the cloud baseline (MCP/RAG/Multi-Agent off)
#   * endpoint security: plain HTTP is redirected to HTTPS, and the services'
#     internal addresses are not reachable from the internet
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/azure-config.sh"

base=${1:-}
if [[ -z $base ]]; then
  require_az_login
  base=$(apps_output appUrl)
fi
base=${base%/}
echo "Target: $base"

# Services may be scaled to zero; the first request wakes them up.
retry=(--retry 20 --retry-delay 6 --retry-all-errors --silent --show-error --fail)
failures=0
fail() { echo "    FAIL: $*"; failures=$((failures + 1)); }

check_url() { # path  [expected substring]
  echo "==> GET $1"
  local body
  if ! body=$(curl "${retry[@]}" --max-time 120 "$base$1"); then
    fail "$1 did not answer 2xx"
    return
  fi
  if [[ -n ${2:-} ]] && ! grep -q "$2" <<<"$body"; then
    fail "$1 did not contain '$2'"
  fi
}

check_url "/" "Plant"
check_url "/auth/login" "Log"
# gunicorn's compact JSON ({"service":"vgarden"}) and Flask's dev server's pretty JSON both match.
check_url "/vgarden/healthz" '"service": *"vgarden"'
check_url "/almanac/" ""
check_url "/health/plant-health-records/" "Plant Health Records"

echo "==> HTTP is redirected to HTTPS (Container Apps ingress, allowInsecure=false)"
code=$(curl --silent --output /dev/null --write-out '%{http_code}' --max-time 30 "${base/https:/http:}/" || true)
[[ $code =~ ^30[1278]$ ]] || fail "expected a redirect for plain HTTP, got '$code'"

echo "==> internal service addresses are not reachable from the internet"
if command -v az >/dev/null && az account show -o none 2>/dev/null; then
  for fqdn in $(az deployment group show -g "$AZURE_RESOURCE_GROUP" -n "$APPS_DEPLOYMENT" \
    --query "properties.outputs.internalFqdns.value.*" -o tsv 2>/dev/null | tr -d '\r'); do
    # Unreachable is either no answer at all (000) or the environment edge's own
    # "Azure Container App - Unavailable" page: the internal app itself never answers.
    # Anything else (the app's own page) means it is exposed.
    body=$(curl --silent --max-time 15 --write-out '\n%{http_code}' "https://$fqdn/" || true)
    code=${body##*$'\n'}
    if [[ $code == 000 ]] || { [[ $code == 404 ]] && grep -q "Azure Container App - Unavailable" <<<"$body"; }; then
      echo "    $fqdn: not reachable from the internet ($code)"
    else
      fail "$fqdn answered $code from the internet"
    fi
  done
else
  echo "    (skipped: not signed in to Azure, cannot read the internal addresses)"
fi

echo "==> the feature smoke suites (CRUD without a model; integrations report the baseline)"
export MCP_ENABLED RAG_ENABLED MULTI_AGENT_ENABLED
bash "$ROOT/scripts/test/smoke-health.sh" "$base" || fail "scripts/test/smoke-health.sh"
bash "$ROOT/scripts/test/smoke-vgarden.sh" "$base" || fail "scripts/test/smoke-vgarden.sh"

if ((failures)); then
  echo "cloud smoke test FAILED ($failures problem(s))"
  exit 1
fi
echo "cloud smoke test passed: $base"

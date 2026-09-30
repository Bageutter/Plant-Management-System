#!/usr/bin/env bash
# Smoke-check the Plant Health service through the nginx proxy.
#
# Used by .github/workflows/health.yml (with MCP_ENABLED=false RAG_ENABLED=false,
# as Release 1 requires during CI) and runnable locally against a running stack:
#
#   MCP_ENABLED=false RAG_ENABLED=false docker compose up -d --build
#   bash scripts/test/smoke-health.sh http://127.0.0.1:3000
#
# It proves: the UI and API answer, /healthz reports the local model state, the
# MCP/RAG integration is *wired* and reports exactly the configured state, and the
# CRUD API behaves without any model call.
set -euo pipefail

base="${1:-http://127.0.0.1:3000}"
health="$base/health"
records="$health/plant-health-records"
retry=(--retry 20 --retry-delay 3 --retry-all-errors --silent --show-error)

as_bool() { case "${1,,}" in 1|true|yes|on) echo true ;; *) echo false ;; esac; }
want_mcp=$(as_bool "${MCP_ENABLED:-true}")
want_rag=$(as_bool "${RAG_ENABLED:-true}")

echo "==> UI: $records/"
curl "${retry[@]}" --fail "$records/" | grep "Plant Health Records" > /dev/null

echo "==> /healthz (200 = model reachable, 503 = degraded; both must be JSON)"
code=$(curl "${retry[@]}" -o /tmp/healthz.json -w '%{http_code}' "$health/healthz" || true)
[[ "$code" == "200" || "$code" == "503" ]] || { echo "unexpected healthz status $code"; cat /tmp/healthz.json; exit 1; }
python3 -c 'import json,sys; d=json.load(open("/tmp/healthz.json")); assert d["service"]=="health-monitoring-service", d'
echo "    healthz -> $code"

echo "==> integrations wired with mcp=$want_mcp rag=$want_rag"
curl "${retry[@]}" --fail "$records/integrations" > /tmp/integrations.json
WANT_MCP="$want_mcp" WANT_RAG="$want_rag" python3 - <<'EOF'
import json, os
d = json.load(open("/tmp/integrations.json"))
want_mcp = os.environ["WANT_MCP"] == "true"
want_rag = os.environ["WANT_RAG"] == "true"
assert d["mcp"]["enabled"] is want_mcp, d
assert d["rag"]["enabled"] is want_rag, d
assert d["mcp"]["url"].endswith("/mcp"), d
print("    ", json.dumps(d))
EOF

if [[ "$want_mcp" == "false" ]]; then
  echo "==> MCP disabled: tool runs must answer 503 without contacting a server"
  code=$(curl --silent -o /tmp/tool.json -w '%{http_code}' -X POST -H 'Content-Type: application/json' \
       -d '{"tool":"health_service_status"}' "$records/tools/run")
  [[ "$code" == "503" ]] || { echo "expected 503, got $code"; cat /tmp/tool.json; exit 1; }
  grep -q disabled /tmp/tool.json
fi
if [[ "$want_rag" == "false" ]]; then
  echo "==> RAG disabled: questions must answer 503 without contacting a server"
  code=$(curl --silent -o /tmp/ask.json -w '%{http_code}' -X POST -H 'Content-Type: application/json' \
       -d '{"question":"Why is the tomato yellow?"}' "$records/ask")
  [[ "$code" == "503" ]] || { echo "expected 503, got $code"; cat /tmp/ask.json; exit 1; }
  grep -q disabled /tmp/ask.json
fi

echo "==> CRUD API without a model call"
curl --fail --silent "$records/assessments?limit=5" | python3 -c 'import json,sys; assert isinstance(json.load(sys.stdin), list)'
code=$(curl --silent -o /dev/null -w '%{http_code}' "$records/assessments/999999")
[[ "$code" == "404" ]] || { echo "expected 404 for a missing record, got $code"; exit 1; }
code=$(curl --silent -o /dev/null -w '%{http_code}' -X POST -H 'Content-Type: application/json' -d '{}' "$records/assessments")
[[ "$code" == "400" ]] || { echo "expected 400 for an empty submission, got $code"; exit 1; }
code=$(curl --silent -o /dev/null -w '%{http_code}' "$records/assessments?status=dead")
[[ "$code" == "400" ]] || { echo "expected 400 for an invalid status filter, got $code"; exit 1; }

echo "health smoke test passed"

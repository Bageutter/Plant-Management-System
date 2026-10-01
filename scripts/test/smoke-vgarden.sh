#!/usr/bin/env bash
# Smoke-check the Virtual Garden service through the nginx proxy.
#
# Used by .github/workflows/vgarden.yml (with MCP_ENABLED=false RAG_ENABLED=false,
# as Release 1 requires during CI) and runnable locally against a running stack:
#
#   MCP_ENABLED=false RAG_ENABLED=false docker compose up -d --build
#   bash scripts/test/smoke-vgarden.sh http://127.0.0.1:3000
#
# It proves: the service answers, the MCP/RAG integration is *wired* and reports
# exactly the configured state (service-level, no login needed), and that garden
# pages still require authentication (unaffected by the Release 1 extension).
set -euo pipefail

base="${1:-http://127.0.0.1:3000}"
vgarden="$base/vgarden"
retry=(--retry 20 --retry-delay 3 --retry-all-errors --silent --show-error)

as_bool() { case "${1,,}" in 1|true|yes|on) echo true ;; *) echo false ;; esac; }
want_mcp=$(as_bool "${MCP_ENABLED:-true}")
want_rag=$(as_bool "${RAG_ENABLED:-true}")

echo "==> $vgarden/healthz"
curl "${retry[@]}" --fail "$vgarden/healthz" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["service"]=="vgarden", d'

echo "==> integrations wired with mcp=$want_mcp rag=$want_rag (service-level, no login needed)"
curl "${retry[@]}" --fail "$vgarden/integrations" > /tmp/vgarden-integrations.json
WANT_MCP="$want_mcp" WANT_RAG="$want_rag" python3 - <<'EOF'
import json, os
d = json.load(open("/tmp/vgarden-integrations.json"))
want_mcp = os.environ["WANT_MCP"] == "true"
want_rag = os.environ["WANT_RAG"] == "true"
assert d["mcp"]["enabled"] is want_mcp, d
assert d["rag"]["enabled"] is want_rag, d
assert d["mcp"]["url"].endswith("/mcp"), d
print("    ", json.dumps(d))
EOF

echo "==> an anonymous visitor is redirected to log in (garden data stays private)"
code=$(curl --silent -o /dev/null -w '%{http_code}' "$vgarden/gardens/1/view")
[[ "$code" == "302" ]] || { echo "expected 302, got $code"; exit 1; }

echo "==> the private snapshot/export endpoints still require the shared service token"
code=$(curl --silent -o /dev/null -w '%{http_code}' "$vgarden/gardens/export")
[[ "$code" == "401" ]] || { echo "expected 401, got $code"; exit 1; }

echo "vgarden smoke test passed"

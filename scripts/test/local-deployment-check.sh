#!/usr/bin/env bash
# Check the whole Release 2 stack running locally and print a transcript for the
# local deployment report:
#
#   - the containers from docker-compose.yml (proxy, frontend, auth, vgarden,
#     almanac, health);
#   - the non-containerised services on the host (AI-Mode/Ollama, MCP, RAG,
#     Multi-Agent Server), and that none of them runs in a container;
#   - that each backend reaches them from inside its container, the way the
#     frontend UI uses them.
#
#   bash scripts/test/local-deployment-check.sh [http://127.0.0.1:3000] | tee local-deployment.txt
#
# Read-only: it only sends GET requests. Exit code 1 if any check fails.
set -uo pipefail

base="${1:-http://127.0.0.1:3000}"
host="${HOST_SERVICES:-127.0.0.1}"
failures=0
compose=(docker compose)

section() { printf '\n=== %s\n' "$*"; }
ok() { printf '  PASS  %s\n' "$*"; }
bad() { printf '  FAIL  %s\n' "$*"; failures=$((failures + 1)); }

# check NAME URL [EXPECTED_SUBSTRING]: GET a URL, PASS on HTTP < 400 (and the text if given).
check() {
  local name=$1 url=$2 want=${3:-} body code
  body=$(curl --silent --show-error --max-time 30 --write-out '\n%{http_code}' "$url" 2>&1)
  code=${body##*$'\n'}
  body=${body%$'\n'*}
  if [[ $code =~ ^[23] ]] && [[ -z $want || $body == *"$want"* ]]; then
    ok "$name  ($url -> HTTP $code)"
  else
    bad "$name  ($url -> HTTP $code${want:+, expected \"$want\"})"
  fi
}

# json NAME URL: print a compact JSON body under a check.
json() {
  local body
  body=$(curl --silent --max-time 30 "$2") || { bad "$1 ($2 unreachable)"; return; }
  ok "$1  ($2)"
  printf '%s' "$body" | python3 -c 'import json,sys; print("        " + json.dumps(json.load(sys.stdin), separators=(",", ":"))[:600])' \
    2>/dev/null || printf '        %s\n' "${body:0:300}"
}

printf 'Local deployment check — %s\n' "$(date -u '+%Y-%m-%d %H:%M:%S UTC')"
printf 'Commit %s on %s\n' "$(git rev-parse --short HEAD)" "$(git branch --show-current)"

section "1. Containers (docker compose)"
"${compose[@]}" ps --format 'table {{.Service}}\t{{.State}}\t{{.Status}}\t{{.Ports}}'
for service in proxy frontend auth vgarden almanac health; do
  state=$("${compose[@]}" ps --format '{{.Service}} {{.State}}' | awk -v s="$service" '$1 == s {print $2}')
  [[ $state == running ]] && ok "$service container is running" || bad "$service container is ${state:-missing}"
done
running=$("${compose[@]}" ps --services)
for name in ollama mcp rag multi-agent; do
  if grep -qi "$name" <<<"$running"; then bad "$name runs as a compose service (must stay on the host)"
  else ok "no '$name' compose service (stays non-containerised)"; fi
done

section "2. Non-containerised services on the host"
for port in 11434 5105 5106 8003; do
  process=$(lsof -nP -iTCP:"$port" -sTCP:LISTEN 2>/dev/null | awk 'NR == 2 {print $1 " pid " $2}')
  printf '  port %-5s %s\n' "$port" "${process:-(nothing listening)}"
done
json "AI-Mode: Ollama version" "http://$host:11434/api/version"
if models=$(curl --silent --max-time 30 "http://$host:11434/api/ps"); then
  ok "AI-Mode: models loaded right now  (http://$host:11434/api/ps)"
  printf '%s' "$models" | python3 -c 'import json,sys; print("        " + ", ".join(m["name"] for m in json.load(sys.stdin)["models"]) or "        (none)")'
else bad "AI-Mode: /api/ps unreachable"; fi
json "MCP server" "http://$host:5105/healthz"
json "RAG server" "http://$host:5106/healthz"
json "Multi-Agent Server" "http://$host:8003/healthz"

section "3. Frontend UI and backends through the proxy ($base)"
check "frontend home page" "$base/" "Plant"
check "auth login page" "$base/auth/login" "Log"
check "vgarden health" "$base/vgarden/healthz" '"vgarden"'
check "almanac catalogue" "$base/almanac/"
check "health records page" "$base/health/plant-health-records/" "Plant Health Records"
json "vgarden: AI integrations it is configured to use" "$base/vgarden/integrations"
json "health: AI status" "$base/health/healthz"

section "4. Backends reach the host services from inside their containers"
reach() { # SERVICE URL
  if "${compose[@]}" exec -T "$1" python -c 'import sys, urllib.request; urllib.request.urlopen(sys.argv[1], timeout=10)' "$2" \
    >/dev/null 2>&1; then ok "$1 -> $2"; else bad "$1 cannot reach $2"; fi
}
for service in vgarden almanac health; do
  reach "$service" http://host.docker.internal:11434/api/version
  reach "$service" http://host.docker.internal:5105/healthz
  reach "$service" http://host.docker.internal:5106/healthz
done
reach vgarden http://host.docker.internal:8003/healthz

section "Result"
if (( failures )); then printf '%d check(s) failed\n' "$failures"; exit 1; fi
printf 'All checks passed\n'

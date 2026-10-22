#!/usr/bin/env bash
# Bring the whole Release 2 demo stack up on the Windows/WSL laptop, for recording.
#
#   wsl -d Ubuntu -- bash -c "bash '/mnt/c/.../scripts/demo/wsl-demo-up.sh'"
#
# Containers run under the WSL Docker engine. AI-Mode (Ollama), the MCP server, the RAG
# server and the Multi-Agent Server run as plain WSL processes bound to all interfaces so the
# containers reach them at host.docker.internal. Ollama is the Linux build copied out of the
# ollama/ollama image into ~/ollama (override with OLLAMA_BIN); its models live in ~/.ollama.
# It picks up the NVIDIA GPU through WSL. The Python servers run from the venv at
# ~/pms-venv (override with PMS_PY), created with the ai-services requirements-dev files.
# The `-demo` model variants are created on first run by scripts/demo/create-demo-models.sh.
#
# After it finishes: http://localhost:3000 (app), http://127.0.0.1:8003/dashboard (agents).
# Re-run safely at any time; it frees the ports it needs and re-syncs the RAG index, which
# the RAG server keeps only in memory.
set -u
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin   # skip Rancher's broken credential helper
unset DOCKER_BUILDKIT                                                        # this engine has no buildx
export COMPOSE_PROJECT_NAME=plant-management-system

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PY="${PMS_PY:-$HOME/pms-venv/bin/python}"
export OLLAMA_BIN="${OLLAMA_BIN:-$HOME/ollama/bin/ollama}"
LOGS=~/pms-logs
mkdir -p "$LOGS"
cd "$REPO" || exit 1
C="docker compose -f docker-compose.yml -f docker-compose.demo.yml"

echo "== 1. Ollama (native WSL, GPU) on 0.0.0.0:11434"
if ! curl -sf -m 2 http://127.0.0.1:11434/api/version >/dev/null; then
  OLLAMA_HOST=0.0.0.0:11434 OLLAMA_KEEP_ALIVE=1h OLLAMA_NUM_PARALLEL=1 \
    setsid nohup "$OLLAMA_BIN" serve > "$LOGS/ollama.log" 2>&1 &
  for i in $(seq 1 30); do curl -sf -m 2 http://127.0.0.1:11434/api/version >/dev/null && break; sleep 1; done
fi
curl -s http://127.0.0.1:11434/api/version; echo

echo "== 1b. the -demo model variants (num_thread 6)"
for m in qwen3:4b-instruct-demo qwen2.5vl:3b-demo; do
  if curl -sf -m 5 http://127.0.0.1:11434/api/show -d "{\"model\":\"$m\"}" >/dev/null; then
    echo "   $m: present"
  else
    bash scripts/demo/create-demo-models.sh "${m%-demo}"
  fi
done

echo "== 2. containers"
$C up -d --build 2>&1 | grep -E "Built|Recreated|Started|Running|Error|error" | tail -10
$C restart proxy >/dev/null 2>&1   # nginx caches backend IPs at startup
$C ps --format "table {{.Service}}\t{{.State}}\t{{.Status}}"

echo "== 3. MCP, RAG and Multi-Agent servers"
for p in 5105 5106 8003; do fuser -k -n tcp $p >/dev/null 2>&1 && echo "   freed port $p"; done
sleep 1
MCP_HOST=0.0.0.0 \
  setsid nohup $PY ai-services/mcp-server/server.py > "$LOGS/mcp-server.log" 2>&1 &
RAG_HOST=0.0.0.0 OLLAMA_MODEL=qwen3:4b-instruct-demo OLLAMA_AUTO_PULL=false \
  setsid nohup $PY ai-services/rag-server/app.py > "$LOGS/rag-server.log" 2>&1 &
( cd ai-services/multi-agent-server && \
  MULTI_AGENT_HOST=0.0.0.0 OLLAMA_MODEL=qwen3:4b-instruct-demo REVIEWER_MODEL=qwen3:4b-instruct-demo \
  setsid nohup $PY app.py > "$LOGS/multi-agent-server.log" 2>&1 & )
for i in $(seq 1 30); do
  curl -sf -m 2 http://127.0.0.1:5105/healthz >/dev/null && curl -sf -m 2 http://127.0.0.1:5106/healthz >/dev/null \
    && curl -sf -m 2 http://127.0.0.1:8003/healthz >/dev/null && break
  sleep 1
done
for p in 5105 5106 8003; do printf "   :%s %s\n" "$p" "$(curl -s -m 5 http://127.0.0.1:$p/healthz | head -c 90)"; done

echo "== 4. warm the models"
for m in qwen3:4b-instruct-demo qwen2.5vl:3b-demo; do
  printf "   %s: " "$m"
  curl -s -m 600 http://127.0.0.1:11434/api/generate -H 'Content-Type: application/json' \
    -d "{\"model\":\"$m\",\"prompt\":\"Say ready.\",\"stream\":false,\"keep_alive\":\"1h\",\"options\":{\"num_predict\":4}}" \
    | $PY -c 'import json,sys; d=json.load(sys.stdin); print("ok" if "response" in d else d)'
done

echo "== 5. re-sync the RAG index (health, almanac; the garden sync needs the owner's login)"
for i in $(seq 1 30); do curl -sf -m 3 http://127.0.0.1:3000/health/plant-health-records/integrations >/dev/null && break; sleep 1; done
printf "   health:  "; curl -s -m 300 -X POST http://127.0.0.1:3000/health/plant-health-records/ask/sync -H 'Accept: application/json' | head -c 120; echo
printf "   almanac: "; curl -s -m 300 -X POST http://127.0.0.1:5106/rag/ingest/almanac | head -c 120; echo
printf "   vgarden: "; curl -s -m 300 -X POST http://127.0.0.1:5106/rag/ingest/vgarden | head -c 120; echo

echo "== 6. deployment check"
bash scripts/test/local-deployment-check.sh http://127.0.0.1:3000 > "$LOGS/local-deployment-check.txt" 2>&1
echo "   exit $? ; $(grep -cE '^\s*PASS' "$LOGS/local-deployment-check.txt") pass, $(grep -cE '^\s*FAIL' "$LOGS/local-deployment-check.txt") fail  (transcript: $LOGS/local-deployment-check.txt)"
echo "Done. App: http://localhost:3000   Agents dashboard: http://127.0.0.1:8003/dashboard"

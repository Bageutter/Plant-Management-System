#!/usr/bin/env bash
# Terminal run of Planner -> Worker -> Reviewer -> Human Review for Plant Health, going
# the same way the records page does: through the health BACKEND, which reads the
# plant's stored assessments (via MCP when it is on) and hands them to the shared
# local Multi-Agent Server as evidence. Needs the stack, the server and Ollama:
#
#   docker compose up -d                                    # the app on :3000
#   python ai-services/multi-agent-server/app.py            # terminal 1
#   bash scripts/test/multi-agent-health.sh "Tomato, back bed"   # terminal 2
#
# Run in a terminal, you make the final human decision. Non-interactive runs
# (DECISION / FEEDBACK env vars, else a cautious default) are for recorded evidence.
set -euo pipefail
HEALTH="${HEALTH:-http://127.0.0.1:3000/health}"
RECORDS="$HEALTH/plant-health-records"
PLANT="${1:-${PLANT:-}}"
TASK="${TASK:-Summarise how the health of this plant has changed across its assessments and which issues keep recurring.}"
show() { python3 -c 'import json,sys; d=json.load(sys.stdin); keys=sys.argv[1:]; print(json.dumps({k: d.get(k) for k in keys} if keys else d, indent=2, ensure_ascii=False))' "$@"; }
json=(-H 'Content-Type: application/json' -H 'Accept: application/json')

echo '$ curl -s $RECORDS/integrations   (the backend reports how it is wired)'
curl -s "$RECORDS/integrations" | show multi_agent mcp

echo; echo "\$ curl -s -X POST \$RECORDS/workflows  (task + plant_ref='$PLANT'; the backend attaches the stored assessments)"
created=$(python3 -c 'import json,sys; print(json.dumps({"task": sys.argv[1], "plant_ref": sys.argv[2]}))' "$TASK" "$PLANT" \
  | curl -s -X POST "$RECORDS/workflows" "${json[@]}" -d @-)
echo "$created" | show id workflow_id status polling plant_ref
local_id=$(echo "$created" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["id"])')

echo; echo "\$ curl -s \$RECORDS/workflows/$local_id   (poll while Planner -> Worker -> Reviewer run on the server)"
time_start=$SECONDS
while :; do
  state=$(curl -s "$RECORDS/workflows/$local_id" "${json[@]}")
  status=$(echo "$state" | python3 -c 'import json,sys; print(json.load(sys.stdin)["status"])')
  echo "  $((SECONDS - time_start))s  $status"
  case "$status" in awaiting_human_review|failed|accepted|partially_accepted|rejected) break ;; esac
  sleep 3
done
echo "$state" | show status plan result review
echo "$state" | python3 -c 'import json,sys; d=json.load(sys.stdin); e=d.get("evidence") or {}; print("evidence:", e.get("mode"), [p["chunk_id"] for p in e.get("passages", [])])'
[[ "$status" == "awaiting_human_review" ]] || { echo "workflow ended as $status"; exit 1; }

echo; echo "\$ curl -s -X POST \$RECORDS/workflows/$local_id/review  decision=request_changes"
curl -s -X POST "$RECORDS/workflows/$local_id/review" "${json[@]}" \
  -d '{"decision": "request_changes", "feedback": "Also list the health score of every assessment, oldest first.", "reviewer": "guhan-terminal"}' | show status polling
echo; echo "  (the backend starts the revised run; feedback goes to the Planner and the Worker)"
time_start=$SECONDS
while :; do
  state=$(curl -s "$RECORDS/workflows/$local_id" "${json[@]}")
  status=$(echo "$state" | python3 -c 'import json,sys; print(json.load(sys.stdin)["status"])')
  echo "  $((SECONDS - time_start))s  $status"
  case "$status" in awaiting_human_review|failed) break ;; esac
  sleep 3
done
echo "$state" | show status revision_feedback plan result review
[[ "$status" == "awaiting_human_review" ]] || { echo "revised run ended as $status"; exit 1; }

recommendation=$(echo "$state" | python3 -c 'import json,sys; print(json.load(sys.stdin)["review"]["recommendation"])')
if [[ -t 0 && -z "${DECISION:-}" ]]; then
  echo; read -r -p "Your decision (accept / partially_accept / request_changes / reject): " DECISION
  read -r -p "Feedback: " FEEDBACK
elif [[ -z "${DECISION:-}" ]]; then
  # Cautious default: never fully accept what the Reviewer flagged.
  if [[ "$recommendation" == "revise" ]]; then
    DECISION=partially_accept
    FEEDBACK="Approved only the claims the Reviewer did not flag; the flagged claims remain unresolved."
  else
    DECISION=accept
    FEEDBACK="Checked against the stored assessments."
  fi
fi
echo; echo "\$ curl -s -X POST \$RECORDS/workflows/$local_id/review  decision=$DECISION  (Reviewer said: $recommendation)"
python3 -c 'import json,sys; print(json.dumps({"decision": sys.argv[1], "feedback": sys.argv[2], "reviewer": "guhan-terminal"}))' "$DECISION" "${FEEDBACK:-}" \
  | curl -s -X POST "$RECORDS/workflows/$local_id/review" "${json[@]}" -d @- | show status human_review error

echo; echo "\$ curl -s \$RECORDS/workflows/$local_id   (history)"
curl -s "$RECORDS/workflows/$local_id" "${json[@]}" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["status"]); [print(" ", e["created_at"][:19], e["status"]) for e in d["history"]]'

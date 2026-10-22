#!/usr/bin/env bash
# Terminal run of Planner -> Worker -> Reviewer -> Human Review for the Plant Almanac on the
# shared local Multi-Agent Server. Almanac data is public, so the task is sent on its own
# (source "almanac") and the Worker retrieves the Almanac records itself through the
# shared MCP server, exactly as the Almanac chat's Multi-Agent mode does.
#
#   ollama serve                                         # terminal 1
#   python ai-services/mcp-server/server.py              # terminal 2 (reads the Almanac API)
#   python ai-services/multi-agent-server/app.py         # terminal 3
#   bash scripts/test/multi-agent-almanac.sh             # terminal 4
#
# Run in a terminal, you make the final human decision; non-interactive runs use
# DECISION / FEEDBACK, else a cautious default (never fully accept what was flagged).
set -euo pipefail
MAS="${MAS:-http://127.0.0.1:8003}"
TASK="${TASK:-What sunlight and soil pH does Basil need, according to the Almanac?}"
CHANGES="${CHANGES:-Also say what the Almanac records about the water needs of Basil.}"
REVIEWER="${REVIEWER:-yunus-terminal}"
show() { python3 -c 'import json,sys; d=json.load(sys.stdin); keys=sys.argv[1:]; print(json.dumps({k: d.get(k) for k in keys} if keys else d, indent=2, ensure_ascii=False))' "$@"; }
field() { python3 -c 'import json,sys; d=json.load(sys.stdin); print(eval(sys.argv[1], {}, {"d": d}))' "$1"; }
post() { curl -s -X POST "$MAS$1" -H 'Content-Type: application/json' -d @-; }

echo '$ curl -s $MAS/healthz'
curl -s "$MAS/healthz"; echo

echo; echo '$ curl -s -X POST $MAS/workflow   (task only: source "almanac"; the Worker retrieves through MCP)'
created=$(python3 -c 'import json,sys; print(json.dumps({"task": sys.argv[1], "source": "almanac"}))' "$TASK" | post /workflow)
echo "$created" | show workflow_id status source
id=$(echo "$created" | field 'd["workflow_id"]')

run() {
  local started=$SECONDS
  python3 -c 'import json,sys; print(json.dumps({"workflow_id": sys.argv[1]}))' "$id" | post /workflow/run > /dev/null
  local elapsed=$((SECONDS - started))
  echo "(agents took ${elapsed}s)" >&2
  curl -s "$MAS/workflow/status?id=$id"
}

echo; echo "\$ curl -s -X POST \$MAS/workflow/run   (Planner -> Worker -> Reviewer)"
state=$(run)
echo "$state" | show status plan result review
echo "$state" | python3 -c 'import json,sys; [print("  evidence:", p["chunk_id"], "-", p["title"]) for p in (json.load(sys.stdin).get("evidence") or {}).get("passages", [])]'

echo; echo '$ curl -s -X POST $MAS/workflow/review  decision=request_changes'
python3 -c 'import json,sys; print(json.dumps({"workflow_id": sys.argv[1], "decision": "request_changes", "feedback": sys.argv[2], "reviewer_id": sys.argv[3]}))' "$id" "$CHANGES" "$REVIEWER" \
  | post /workflow/review | show status human_review

echo; echo '$ curl -s -X POST $MAS/workflow/run   (revised run; the feedback goes to the Planner and Worker)'
state=$(run)
echo "$state" | show status revision_feedback plan result review

recommendation=$(echo "$state" | field 'd["review"]["recommendation"]')
if [[ -t 0 && -z "${DECISION:-}" ]]; then
  echo; read -r -p "Your decision (accept / partially_accept / request_changes / reject): " DECISION
  read -r -p "Feedback: " FEEDBACK
elif [[ -z "${DECISION:-}" ]]; then
  if [[ "$recommendation" == "revise" ]]; then
    DECISION=partially_accept
    FEEDBACK="Approved only the claims the Reviewer did not flag; the flagged claims remain unresolved."
  else
    DECISION=accept
    FEEDBACK="Checked against the Almanac records."
  fi
fi
echo; echo "\$ curl -s -X POST \$MAS/workflow/review  decision=$DECISION  (Reviewer said: $recommendation)"
python3 -c 'import json,sys; print(json.dumps({"workflow_id": sys.argv[1], "decision": sys.argv[2], "feedback": sys.argv[3], "reviewer_id": sys.argv[4]}))' \
  "$id" "$DECISION" "${FEEDBACK:-}" "$REVIEWER" | post /workflow/review | show status human_review error

echo; echo "\$ curl -s \"\$MAS/workflow/status?id=$id\"   (history)"
curl -s "$MAS/workflow/status?id=$id" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["status"], d["workflow_id"]); [print(" ", e["created_at"][:19], e["status"]) for e in d["history"]]'

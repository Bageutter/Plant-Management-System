#!/usr/bin/env bash
# Terminal run of Planner -> Worker -> Reviewer -> Human Review for Plant Health,
# through the health backend's own JSON API (the same routes the UI panel uses), so
# the evidence is the real assessment built by workflows.py::assessment_evidence.
#
#   python ai-services/multi-agent-server/app.py                       # terminal 1
#   docker compose up -d   (or run health directly)                     # terminal 2
#   bash scripts/test/multi-agent-health.sh [health base URL]           # terminal 3
#
# HEALTH defaults to http://127.0.0.1:3000/health/plant-health-records. ASSESSMENT
# picks the record (default: the newest). Run in a terminal, you make the final
# human decision; non-interactive runs use DECISION / FEEDBACK, else a cautious default.
set -euo pipefail
HEALTH="${1:-${HEALTH:-http://127.0.0.1:3000/health/plant-health-records}}"
TASK="${TASK:-Which recorded issue needs attention first, and what does the record say to do about it?}"
CHANGES="${CHANGES:-Also say what information the assessment says is missing.}"
REVIEWER="${REVIEWER:-yunus-terminal}"
json=(-H 'Content-Type: application/json' -H 'Accept: application/json')
show() { python3 -c 'import json,sys; d=json.load(sys.stdin); keys=sys.argv[1:]; print(json.dumps({k: d.get(k) for k in keys} if keys else d, indent=2, ensure_ascii=False))' "$@"; }
field() { python3 -c 'import json,sys; d=json.load(sys.stdin); print(eval(sys.argv[1], {}, {"d": d}))' "$1"; }

echo '$ curl -s $HEALTH/integrations'
curl -s "$HEALTH/integrations" | show multi_agent

assessment="${ASSESSMENT:-$(curl -s "$HEALTH/assessments?limit=1" -H 'Accept: application/json' | field 'd["assessments"][0]["id"] if isinstance(d, dict) and d.get("assessments") else d[0]["id"]')}"
echo; echo "\$ curl -s $HEALTH/assessments/$assessment"
curl -s "$HEALTH/assessments/$assessment" -H 'Accept: application/json' | show plant_ref status health_score confidence summary

wait_for_review() { # poll until the agents finish
  local started=$SECONDS state status
  while true; do
    state=$(curl -s "$HEALTH/assessments/$assessment/workflows/$local_id" -H 'Accept: application/json')
    status=$(echo "$state" | field 'd.get("status")')
    case "$status" in planning|working|reviewing|received|changes_requested) sleep 3 ;; *) break ;; esac
  done
  echo "(agents took $((SECONDS - started))s)" >&2
  echo "$state"
}

echo; echo "\$ curl -s -X POST $HEALTH/assessments/$assessment/workflows  (task; health sends this assessment's records)"
created=$(python3 -c 'import json,sys; print(json.dumps({"task": sys.argv[1]}))' "$TASK" \
  | curl -s -X POST "$HEALTH/assessments/$assessment/workflows" "${json[@]}" -d @-)
echo "$created" | show id workflow_id status source
local_id=$(echo "$created" | field 'd["id"]')
state=$(wait_for_review)
echo "$state" | show status plan result review
echo "$state" | python3 -c 'import json,sys; [print("  evidence:", p["chunk_id"], "-", p["title"]) for p in json.load(sys.stdin)["evidence"]["passages"]]'

echo; echo '$ curl -s -X POST .../review  decision=request_changes'
python3 -c 'import json,sys; print(json.dumps({"decision": "request_changes", "feedback": sys.argv[1], "reviewer_id": sys.argv[2]}))' "$CHANGES" "$REVIEWER" \
  | curl -s -X POST "$HEALTH/assessments/$assessment/workflows/$local_id/review" "${json[@]}" -d @- | show status human_review
echo '(the health backend starts the revised run; feedback goes to the Planner and Worker)'
state=$(wait_for_review)
echo "$state" | show status revision_feedback plan result review

recommendation=$(echo "$state" | field 'd["review"]["recommendation"]')
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
    FEEDBACK="Checked against the assessment record."
  fi
fi
echo; echo "\$ curl -s -X POST .../review  decision=$DECISION  (Reviewer said: $recommendation)"
python3 -c 'import json,sys; print(json.dumps({"decision": sys.argv[1], "feedback": sys.argv[2], "reviewer_id": sys.argv[3]}))' \
  "$DECISION" "${FEEDBACK:-}" "$REVIEWER" \
  | curl -s -X POST "$HEALTH/assessments/$assessment/workflows/$local_id/review" "${json[@]}" -d @- | show status human_review error

echo; echo "\$ curl -s $HEALTH/assessments/$assessment/workflows/$local_id   (history)"
curl -s "$HEALTH/assessments/$assessment/workflows/$local_id" -H 'Accept: application/json' \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["status"], d["workflow_id"]); [print(" ", e["created_at"][:19], e["status"]) for e in d["history"]]'

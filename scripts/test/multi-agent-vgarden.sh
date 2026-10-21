#!/usr/bin/env bash
# Terminal run of Planner -> Worker -> Reviewer -> Human Review on the shared local
# Multi-Agent Server, with Virtual Garden evidence (the same shape vgarden sends from
# garden_workflows.py::garden_evidence). Needs the server and Ollama running:
#
#   python ai-services/multi-agent-server/app.py          # terminal 1
#   bash scripts/test/multi-agent-vgarden.sh              # terminal 2
#
# Run in a terminal, you make the final human decision. Non-interactive runs
# (DECISION / FEEDBACK env vars, else a cautious default) are for recorded evidence.
set -euo pipefail
MAS="${MAS:-http://127.0.0.1:8003}"
show() { python3 -c 'import json,sys; d=json.load(sys.stdin); keys=sys.argv[1:]; print(json.dumps({k: d.get(k) for k in keys} if keys else d, indent=2, ensure_ascii=False))' "$@"; }

echo '$ curl -s $MAS/healthz'
curl -s "$MAS/healthz"; echo

echo; echo '$ curl -s -X POST $MAS/workflow  (task + source=vgarden + this garden'"'"'s records)'
created=$(curl -s -X POST "$MAS/workflow" -H 'Content-Type: application/json' -d @- <<'JSON'
{"task": "Which plantings in the North bed are flowering, and when were they planted?",
 "source": "vgarden",
 "evidence": {"mode": "vgarden-api", "passages": [
  {"chunk_id": "garden-1-summary", "title": "Backyard summary — Virtual Garden record",
   "text": "Garden name: Backyard\nLocation: Melbourne\nClimate zone: temperate\nRecorded: 1 area(s), 0 container(s), 2 planting(s)"},
  {"chunk_id": "garden-1-areas", "title": "Backyard areas — Virtual Garden record",
   "text": "North bed (bed, 2.0 x 3.0 m)"},
  {"chunk_id": "garden-1-plantings", "title": "Backyard plantings — Virtual Garden record",
   "text": "Basil - quantity 6; status sown; growth stage not recorded; location area: North bed; planted 2026-10-05; expected harvest not recorded\nTomato - quantity 3; status growing; growth stage flowering; location area: North bed; planted 2026-09-01; expected harvest not recorded"}]}}
JSON
)
echo "$created" | show
id=$(echo "$created" | python3 -c 'import json,sys; print(json.load(sys.stdin)["workflow_id"])')

echo; echo '$ curl -s -X POST $MAS/workflow/run -d {"workflow_id": "'"$id"'"}   (Planner -> Worker -> Reviewer)'
time_start=$SECONDS
curl -s -X POST "$MAS/workflow/run" -H 'Content-Type: application/json' -d "{\"workflow_id\": \"$id\"}" | show status plan result review
echo "(agents took $((SECONDS - time_start))s)"

echo; echo '$ curl -s -X POST $MAS/workflow/review  decision=request_changes'
curl -s -X POST "$MAS/workflow/review" -H 'Content-Type: application/json' \
  -d "{\"workflow_id\": \"$id\", \"decision\": \"request_changes\", \"reviewer_id\": \"yunus-terminal\", \"feedback\": \"Also say how many tomato plants there are.\"}" | show status human_review

echo; echo '$ curl -s -X POST $MAS/workflow/run   (revised run; feedback goes to the Planner)'
time_start=$SECONDS
curl -s -X POST "$MAS/workflow/run" -H 'Content-Type: application/json' -d "{\"workflow_id\": \"$id\"}" | show status revision_feedback plan result review
echo "(agents took $((SECONDS - time_start))s)"

revised=$(curl -s "$MAS/workflow/status?id=$id")
recommendation=$(echo "$revised" | python3 -c 'import json,sys; print(json.load(sys.stdin)["review"]["recommendation"])')
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
    FEEDBACK="Checked against the garden records."
  fi
fi
echo; echo "\$ curl -s -X POST \$MAS/workflow/review  decision=$DECISION  (Reviewer said: $recommendation)"
python3 -c 'import json,sys; print(json.dumps({"workflow_id": sys.argv[1], "decision": sys.argv[2], "feedback": sys.argv[3], "reviewer_id": "yunus-terminal"}))' \
  "$id" "$DECISION" "${FEEDBACK:-}" \
  | curl -s -X POST "$MAS/workflow/review" -H 'Content-Type: application/json' -d @- | show status human_review error

echo; echo '$ curl -s "$MAS/workflow/status?id='"$id"'"   (history)'
curl -s "$MAS/workflow/status?id=$id" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["status"]); [print(" ", e["created_at"][:19], e["status"]) for e in d["history"]]'

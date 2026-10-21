from uuid import uuid4

from flask import Flask, Response, jsonify, request, render_template

from audit import jsonl, metrics, records

from human_review import record_decision
from store import WorkflowConflict, get_workflow, save_workflow, read_snapshot, recover_interrupted
from workflow import run_workflow

SOURCES = ("almanac", "vgarden", "health")
# Sources whose backend must send its own records: the server never reads them itself.
SUPPLIED_EVIDENCE = ("vgarden", "health")

app = Flask(__name__)
recover_interrupted()


@app.get("/healthz")
def healthz():
    return jsonify({"service": "multi-agent-server", "status": "ok"})


@app.post("/workflow")
def create_workflow():
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({"error": "Send a JSON object"}), 400

    task = data.get("task")

    if not isinstance(task, str) or not 1 <= len(task.strip()) <= 500:
        return jsonify({"error": "task must be 1 to 500 characters"}), 400

    try:
        request_details = _request_details(data)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    workflow_id = str(uuid4())
    task = task.strip()
    save_workflow(workflow_id, task, request_details)

    return jsonify({
        "workflow_id": workflow_id,
        "task": task,
        "source": request_details["source"],
        "status": "received",
    }), 201


def _request_details(data):
    """Validate the optional feature source and caller-supplied evidence.

    Almanac data is public, so its Worker retrieves evidence itself through MCP.
    Virtual Garden data is private per owner, and a Plant Health task is about one
    assessment: this server never fetches either, so the feature backend must send
    the records it already authorised (one garden, or one assessment and its plant's
    history).
    """
    source = data.get("source", "almanac")
    if source not in SOURCES:
        raise ValueError(f"source must be one of: {', '.join(SOURCES)}")
    evidence = data.get("evidence")
    if evidence is None:
        if source in SUPPLIED_EVIDENCE:
            raise ValueError(f"{source} workflows must include the feature's evidence")
        return {"source": source}
    passages = evidence.get("passages") if isinstance(evidence, dict) else None
    if not isinstance(passages, list) or not 1 <= len(passages) <= 10:
        raise ValueError("evidence.passages must be a list of 1 to 10 passages")
    for passage in passages:
        if (not isinstance(passage, dict)
                or any(not isinstance(passage.get(key), str) or not passage[key].strip()
                       for key in ("chunk_id", "title", "text"))
                or len(passage["text"]) > 4000):
            raise ValueError("each passage needs chunk_id, title and text (up to 4000 characters)")
    if len({p["chunk_id"] for p in passages}) != len(passages):
        raise ValueError("passage chunk_id values must be unique")
    mode = evidence.get("mode", "supplied")
    clean = {"mode": mode if isinstance(mode, str) else "supplied",
             "passages": [{key: p[key] for key in ("chunk_id", "title", "text")} for p in passages]}
    return {"source": source, "evidence": clean}


@app.get("/workflow/status")
def workflow_status():
    workflow_id = request.args.get("id", "").strip()
    if not workflow_id:
        return jsonify({"error": "id is required"}), 400

    workflow = get_workflow(workflow_id)
    if workflow is None:
        return jsonify({"error": "Workflow not found"}), 404

    return jsonify(workflow)


@app.post("/workflow/run")
def workflow_run():
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get("workflow_id"), str):
        return jsonify({"error": "workflow_id is required"}), 400
    try:
        return jsonify(run_workflow(data["workflow_id"].strip()))
    except LookupError as error:
        return jsonify({"error": str(error)}), 404
    except WorkflowConflict as error:
        return jsonify({"error": str(error)}), 409
    except RuntimeError as error:
        return jsonify({"error": str(error)}), 502


@app.post("/workflow/review")
def workflow_review():
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get("workflow_id"), str):
        return jsonify({"error": "workflow_id is required"}), 400
    try:
        return jsonify(record_decision(
            data["workflow_id"].strip(), data.get("decision"),
            data.get("feedback", ""), data.get("reviewer_id"),
        ))
    except LookupError as error:
        return jsonify({"error": str(error)}), 404
    except WorkflowConflict as error:
        return jsonify({"error": str(error)}), 409
    except ValueError as error:
        return jsonify({"error": str(error)}), 400


@app.get("/dashboard")
def dashboard():
    snapshot = read_snapshot()
    data = metrics(snapshot)
    models = {}
    if data["latest_agent_run"]:
        for event in reversed(snapshot["events"]):
            if (event["workflow_id"] == data["latest_agent_run"]["workflow_id"]
                    and event["status"] == "planning"
                    and (event["details"].get("run_id") or f"legacy-{event['sequence']}")
                    == data["latest_agent_run"]["run_id"]):
                models = event["details"].get("models", {})
                break
    return render_template("dashboard.html", data=data, models=models,
                           workflows=list(reversed(snapshot["workflows"])))


@app.get("/workflow/metrics")
def workflow_metrics():
    return jsonify(metrics())


@app.get("/workflow/audit/<filename>")
def workflow_audit(filename):
    if filename not in ("workflow_history.jsonl", "coordination_audit.jsonl"):
        return jsonify({"error": "Unknown audit file"}), 404
    history, decisions = records(read_snapshot())
    rows = history if filename == "workflow_history.jsonl" else decisions
    return Response(jsonl(rows), mimetype="application/x-ndjson",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8003)

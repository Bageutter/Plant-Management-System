from uuid import uuid4

from flask import Flask, Response, jsonify, request, render_template

from audit import jsonl, metrics, records

from human_review import record_decision
from store import WorkflowConflict, get_workflow, save_workflow, read_snapshot, recover_interrupted
from workflow import run_workflow

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

    workflow_id = str(uuid4())
    task = task.strip()
    save_workflow(workflow_id, task)

    return jsonify({
        "workflow_id": workflow_id,
        "task": task,
        "status": "received",
    }), 201


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

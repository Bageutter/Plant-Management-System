from uuid import uuid4

from flask import Flask, jsonify, request

from store import save_workflow

app = Flask(__name__)


@app.get("/healthz")
def healthz():
    return jsonify({"service": "multi-agent-server", "status": "ok"})


@app.post("/workflow")
def create_workflow():
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({"error": "Send a JSON object"}), 400

    task = data.get("task")

    if not isinstance(task, str) or not task.strip():
        return jsonify({"error": "task must be non-empty text"}), 400

    workflow_id = str(uuid4())
    task = task.strip()
    save_workflow(workflow_id, task)

    return jsonify({
        "workflow_id": workflow_id,
        "task": task,
        "status": "received",
    }), 201


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8003)

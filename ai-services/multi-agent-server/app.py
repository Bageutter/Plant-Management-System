from flask import Flask, jsonify

app = Flask(__name__)


@app.get("/healthz")
def healthz():
    return jsonify({"service": "multi-agent-server", "status": "ok"})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8003)
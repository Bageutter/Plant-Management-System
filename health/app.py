import json
import os
import sys

from dotenv import load_dotenv
from flask import Flask, Response, jsonify, request
from jinja2 import ChoiceLoader, FileSystemLoader
from werkzeug.middleware.proxy_fix import ProxyFix

# The shared agentic-loop module (shared/ai_loop.py) is mounted at /app/ai_loop.py in
# the container and lives at ../shared/ai_loop.py for local/test runs.
_SHARED = os.path.join(os.path.abspath(os.path.dirname(__file__)), "..", "shared")
if os.path.isdir(_SHARED) and _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)

# Keep imports at module top; delay importing `Config` until after loading env vars
from agentic import HealthAssessmentLoop, build_reviewer
from ai import OllamaClient
from db_upgrade import upgrade_database
from extensions import db, migrate
from images import format_bytes, upload_limit_message
from integrations import McpToolClient, RagClient


def _sse_payload(event: dict) -> str:
    """One server-sent event carrying ``event`` as JSON."""

    return "data: " + json.dumps(event) + "\n\n"


def create_app(config_class: type | None = None) -> Flask:
    # Load environment variables before importing configuration that reads them.
    load_dotenv()

    if config_class is None:
        from config import Config

        config_class = Config

    app = Flask(__name__)
    app.config.from_object(config_class)
    # Behind the nginx proxy this service is mounted under /health; honour
    # X-Forwarded-* so url_for()/redirects carry that prefix. No-op without the
    # headers (direct/local runs).
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
    # Shared project templates (the nav header). In compose they are mounted at
    # ./shared_templates; outside compose (tests, local runs) fall back to the
    # repository's shared/templates directory.
    here = os.path.abspath(os.path.dirname(__file__))
    shared_dirs = [
        os.path.join(here, "shared_templates"),
        os.path.join(here, "..", "shared", "templates"),
    ]
    app.jinja_loader = ChoiceLoader(
        [app.jinja_loader, *(FileSystemLoader(d) for d in shared_dirs if os.path.isdir(d))]
    )

    db_uri = app.config["SQLALCHEMY_DATABASE_URI"]
    if db_uri.startswith("sqlite:///"):
        os.makedirs(os.path.dirname(db_uri.removeprefix("sqlite:///")), exist_ok=True)

    db.init_app(app)
    migrate.init_app(app, db, directory=os.path.join(here, "migrations"))

    app.extensions["ollama"] = OllamaClient(
        base_url=app.config["OLLAMA_URL"],
        model=app.config["OLLAMA_MODEL"],
        timeout=app.config["OLLAMA_TIMEOUT"],
        auto_pull=app.config["OLLAMA_AUTO_PULL"],
        pull_timeout=app.config["OLLAMA_PULL_TIMEOUT"],
        keep_alive=app.config["OLLAMA_KEEP_ALIVE"],
        num_predict=app.config["OLLAMA_NUM_PREDICT"],
        num_ctx=app.config["OLLAMA_NUM_CTX"],
    )
    # Perceive -> Reason -> Act -> Observe -> Repeat around every assessment (agentic.py).
    # The reviewer is an independent text model; None (no OLLAMA_REVIEW_MODEL, or the
    # shared module is not mounted) means the loop runs with the code checks only.
    app.extensions["ai_loop_reviewer"] = build_reviewer(app.config)
    app.extensions["health_loop"] = HealthAssessmentLoop(
        client=lambda: app.extensions["ollama"],
        reviewer=lambda: app.extensions["ai_loop_reviewer"],
        log_dir=app.config.get(
            "AI_LOOP_LOG_DIR", os.path.join(here, "..", "tools", "ai-loop", "logs")
        ),
        max_iterations=app.config.get("AI_LOOP_MAX_ITERATIONS", 2),
    )
    if app.config.get("OLLAMA_PRELOAD", True):
        # Warm the model in the background so the first assessment is fast. Never
        # blocks startup; progress is reported on /healthz.
        app.extensions["ollama"].start_preload(
            retries=app.config.get("OLLAMA_PRELOAD_RETRIES", 12),
            delay=app.config.get("OLLAMA_PRELOAD_RETRY_SECONDS", 5.0),
        )

    # Release 1: clients for the shared local MCP and RAG servers. The browser only
    # ever reaches them through this backend (see routes.py).
    app.extensions["mcp"] = McpToolClient(
        app.config["MCP_SERVER_URL"],
        enabled=app.config["MCP_ENABLED"],
        timeout=app.config["INTEGRATION_TIMEOUT"],
    )
    app.extensions["rag"] = RagClient(
        app.config["RAG_SERVER_URL"],
        enabled=app.config["RAG_ENABLED"],
        timeout=app.config["INTEGRATION_TIMEOUT"],
    )

    from routes import bp as health_bp
    from routes import root_bp

    app.register_blueprint(health_bp)
    app.register_blueprint(root_bp)

    @app.errorhandler(413)
    def payload_too_large(_error):
        limit = app.config["MAX_CONTENT_LENGTH"]
        message = upload_limit_message(limit)
        if request.path.endswith("/stream"):
            # The streaming endpoints are consumed as server-sent events, so answer
            # in that shape too: a naive SSE reader then still sees the reason.
            return Response(
                _sse_payload({"type": "error", "message": message, "limit_bytes": limit}),
                status=413,
                mimetype="text/event-stream",
                headers={"Cache-Control": "no-cache"},
            )
        return jsonify({"error": message, "limit_bytes": limit}), 413

    @app.context_processor
    def inject_template_globals():
        from ai import CONFIDENCE_EXPLANATION, SCORE_EXPLANATION
        from integrations import TOOL_LABELS

        return {
            "mcp_enabled": app.extensions["mcp"].enabled,
            "rag_enabled": app.extensions["rag"].enabled,
            "mcp_tools": TOOL_LABELS,
            "auth_public_url": app.config["AUTH_PUBLIC_URL"],
            "health_public_url": app.config.get(
                "HEALTH_PUBLIC_URL", "http://localhost:5003/plant-health-records/"
            ),
            "almanac_public_url": app.config.get(
                "ALMANAC_PUBLIC_URL", "http://localhost:5004/"
            ),
            "ai_model": app.config["OLLAMA_MODEL"],
            # The upload form tells the user the limit up front and shrinks
            # oversized photos in the browser before they are sent.
            "max_upload_bytes": app.config["MAX_CONTENT_LENGTH"],
            "max_upload_label": format_bytes(app.config["MAX_CONTENT_LENGTH"]),
            "image_max_edge": app.config["IMAGE_MAX_EDGE"],
            "score_explanation": SCORE_EXPLANATION,
            "confidence_explanation": CONFIDENCE_EXPLANATION,
        }

    # Import models so the metadata Alembic compares against is complete.
    import models  # noqa: F401

    # Schema is versioned (Flask-Migrate); see db_upgrade.py and migrations/.
    if app.config.get("AUTO_MIGRATE", True):
        upgrade_database(app)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

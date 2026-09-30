import os

from dotenv import load_dotenv
from flask import Flask, jsonify
from jinja2 import ChoiceLoader, FileSystemLoader
from werkzeug.middleware.proxy_fix import ProxyFix

# Keep imports at module top; delay importing `Config` until after loading env vars
from ai import OllamaClient
from extensions import db
from integrations import McpToolClient, RagClient
from schema import sync_schema


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
        return jsonify({"error": f"Upload exceeds the {limit} byte limit"}), 413

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
            "score_explanation": SCORE_EXPLANATION,
            "confidence_explanation": CONFIDENCE_EXPLANATION,
        }

    with app.app_context():
        # Import models so create_all() and the schema sync see every table.
        import models  # noqa: F401

        db.create_all()
        # create_all() does not alter existing tables, so reconcile added columns.
        sync_schema(db)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

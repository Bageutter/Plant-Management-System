import os

from dotenv import load_dotenv
from flask import Flask, jsonify

load_dotenv()

from ai import OllamaClient
from config import Config
from extensions import db
from schema import sync_schema


def create_app(config_class: type = Config) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config_class)

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

        return {
            "auth_public_url": app.config["AUTH_PUBLIC_URL"],
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

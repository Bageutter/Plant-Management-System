import os

from flask import Flask, current_app, g, jsonify, render_template, request
from jinja2 import ChoiceLoader, FileSystemLoader
from sqlalchemy import text
from werkzeug.middleware.proxy_fix import ProxyFix

from ai import AIUnavailableError, OllamaAlmanacAI
from auth_client import AuthClient
from extensions import db
from models import AIChatMessage, PlantReference
from seed_data import seed_reference_data


BASE_DIR = os.path.abspath(os.path.dirname(__file__))
CHAT_HISTORY_LIMIT = 20


def _records_for_question(question: str, records: list[PlantReference]) -> list[PlantReference]:
    question_lower = question.lower()
    matches = [
        record
        for record in records
        if record.slug.lower() in question_lower
        or record.common_name.lower() in question_lower
        or record.scientific_name.lower() in question_lower
    ]
    return matches or records


def _current_auth_user() -> dict | None:
    if "auth_user" not in g:
        g.auth_user = current_app.extensions["auth_client"].current_user(
            request.headers.get("Cookie", "")
        )
    return g.auth_user


def _chat_owner_key() -> str | None:
    user = _current_auth_user()
    return f"user:{user['id']}" if user else None


def _chat_history(owner_key: str) -> list[AIChatMessage]:
    messages = (
        AIChatMessage.query.filter_by(owner_key=owner_key)
        .order_by(AIChatMessage.id.desc())
        .limit(CHAT_HISTORY_LIMIT)
        .all()
    )
    return list(reversed(messages))


def _chat_context(owner_key: str) -> tuple[list[AIChatMessage], dict[str, dict]]:
    messages = _chat_history(owner_key)
    source_slugs = {
        slug for message in messages for slug in (message.source_slugs or [])
    }
    source_records = PlantReference.query.filter(PlantReference.slug.in_(source_slugs)).all()
    sources = {record.slug: record.to_dict() for record in source_records}
    return messages, sources


def _render_chat(owner_key: str, error: str | None = None):
    messages, sources = _chat_context(owner_key)
    return render_template("_ai_history.html", messages=messages, sources=sources, error=error)


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__, template_folder="templates")
    # Behind the nginx proxy this service is mounted under /almanac; honour
    # X-Forwarded-* so url_for()/redirects carry that prefix. No-op without the
    # headers (direct/local runs).
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
    app.jinja_loader = ChoiceLoader(
        [
            app.jinja_loader,
            FileSystemLoader(
                [
                    os.path.join(BASE_DIR, "shared_templates"),
                    os.path.join(BASE_DIR, "..", "shared", "templates"),
                ]
            ),
        ]
    )
    app.config.from_mapping(
        SQLALCHEMY_DATABASE_URI=os.environ.get(
            "DATABASE_URL",
            "sqlite:///" + os.path.join(BASE_DIR, "instance", "almanac.db"),
        ),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        AUTH_URL=os.environ.get("AUTH_URL", "http://localhost:5001"),
        AUTH_PUBLIC_URL=os.environ.get("AUTH_PUBLIC_URL", "http://localhost:5001"),
        HEALTH_PUBLIC_URL=os.environ.get(
            "HEALTH_PUBLIC_URL", "http://localhost:5003/plant-health-records/"
        ),
        OLLAMA_URL=os.environ.get("OLLAMA_URL", "http://localhost:11434"),
        OLLAMA_MODEL=os.environ.get("OLLAMA_MODEL", "qwen3:4b-instruct"),
        OLLAMA_TIMEOUT=int(os.environ.get("OLLAMA_TIMEOUT", "120")),
        OLLAMA_AUTO_PULL=os.environ.get("OLLAMA_AUTO_PULL", "false").lower() == "true",
    )
    if test_config:
        app.config.update(test_config)

    db_uri = app.config["SQLALCHEMY_DATABASE_URI"]
    if db_uri.startswith("sqlite:///"):
        database_directory = os.path.dirname(db_uri.removeprefix("sqlite:///"))
        if database_directory:
            os.makedirs(database_directory, exist_ok=True)

    db.init_app(app)
    app.extensions["auth_client"] = AuthClient(app.config["AUTH_URL"])
    app.extensions["almanac_ai"] = OllamaAlmanacAI(
        base_url=app.config["OLLAMA_URL"],
        model=app.config["OLLAMA_MODEL"],
        timeout=app.config["OLLAMA_TIMEOUT"],
        auto_pull=app.config.get("OLLAMA_AUTO_PULL", False),
    )

    @app.context_processor
    def inject_service_urls():
        return {
            "auth_public_url": app.config["AUTH_PUBLIC_URL"],
            "health_public_url": app.config["HEALTH_PUBLIC_URL"],
            "auth_user": _current_auth_user(),
        }

    @app.get("/")
    def index():
        plants = PlantReference.query.order_by(PlantReference.common_name).all()
        plants = [p.to_dict() for p in plants]
        owner_key = _chat_owner_key()
        messages, sources = _chat_context(owner_key) if owner_key else ([], {})
        return render_template(
            "index.html",
            plants=plants,
            messages=messages,
            sources=sources,
        )

    @app.get("/plants/<slug>")
    def plant_detail(slug: str):
        plant = PlantReference.query.filter_by(slug=slug).first()
        if plant is None:
            return render_template("404.html"), 404
        return render_template("plant_detail.html", plant=plant.to_dict())

    @app.get("/api/plants")
    def api_plants():
        records = PlantReference.query.order_by(PlantReference.common_name).all()
        return jsonify({"count": len(records), "items": [r.to_dict() for r in records]})

    @app.get("/api/plants/<slug>")
    def api_plant(slug: str):
        record = PlantReference.query.filter_by(slug=slug).first()
        if record is None:
            return jsonify({"error": "plant reference not found"}), 404
        return jsonify(record.to_dict())

    @app.post("/ai/ask")
    def ask_almanac():
        owner_key = _chat_owner_key()
        if owner_key is None:
            return _render_chat(None, "Your session has expired. Log in again to use the chat."), 401
        question = request.form.get("question", "").strip()
        if not question:
            return _render_chat(owner_key, "Enter a question first."), 400
        if len(question) > 500:
            return _render_chat(owner_key, "Keep your question under 500 characters."), 400

        all_records = PlantReference.query.order_by(PlantReference.common_name).all()
        records = _records_for_question(question, all_records)
        plants = [record.to_dict() for record in records]
        try:
            result = app.extensions["almanac_ai"].ask(question, plants)
        except AIUnavailableError:
            return _render_chat(
                owner_key,
                "The local AI model is unavailable. Check that Ollama is running and try again.",
            ), 503

        db.session.add_all(
            [
                AIChatMessage(owner_key=owner_key, role="user", content=question),
                AIChatMessage(
                    owner_key=owner_key,
                    role="assistant",
                    content=result["answer"],
                    source_slugs=result["sources"],
                ),
            ]
        )
        db.session.commit()
        return _render_chat(owner_key)

    @app.post("/ai/clear")
    def clear_ai_chat():
        owner_key = _chat_owner_key()
        if owner_key is None:
            return _render_chat(None, "Your session has expired. Log in again to use the chat."), 401
        AIChatMessage.query.filter_by(owner_key=owner_key).delete()
        db.session.commit()
        return _render_chat(owner_key)

    @app.get("/health")
    def health():
        db.session.execute(text("SELECT 1"))
        return jsonify({"status": "ok", "service": "almanac"})

    with app.app_context():
        db.create_all()
        if not PlantReference.query.first():
            seed_reference_data()

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

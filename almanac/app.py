import os

from flask import Flask, jsonify, render_template, request
from sqlalchemy import text

from ai import AIUnavailableError, OllamaAlmanacAI
from extensions import db
from models import PlantReference
from seed_data import seed_reference_data


BASE_DIR = os.path.abspath(os.path.dirname(__file__))


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


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__, template_folder="templates")
    app.config.from_mapping(
        SQLALCHEMY_DATABASE_URI=os.environ.get(
            "DATABASE_URL",
            "sqlite:///" + os.path.join(BASE_DIR, "instance", "almanac.db"),
        ),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        AUTH_PUBLIC_URL=os.environ.get("AUTH_PUBLIC_URL", "http://localhost:5001"),
        OLLAMA_URL=os.environ.get("OLLAMA_URL", "http://localhost:11434"),
        OLLAMA_MODEL=os.environ.get("OLLAMA_MODEL", "qwen3:4b-instruct"),
        OLLAMA_TIMEOUT=int(os.environ.get("OLLAMA_TIMEOUT", "120")),
    )
    if test_config:
        app.config.update(test_config)

    db_uri = app.config["SQLALCHEMY_DATABASE_URI"]
    if db_uri.startswith("sqlite:///"):
        database_directory = os.path.dirname(db_uri.removeprefix("sqlite:///"))
        if database_directory:
            os.makedirs(database_directory, exist_ok=True)

    db.init_app(app)
    app.extensions["almanac_ai"] = OllamaAlmanacAI(
        base_url=app.config["OLLAMA_URL"],
        model=app.config["OLLAMA_MODEL"],
        timeout=app.config["OLLAMA_TIMEOUT"],
    )

    @app.context_processor
    def inject_service_urls():
        return {"auth_public_url": app.config["AUTH_PUBLIC_URL"]}

    @app.get("/")
    def index():
        plants = PlantReference.query.order_by(PlantReference.common_name).all()
        plants = [p.to_dict() for p in plants]
        return render_template("index.html", plants=plants)

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
        question = request.form.get("question", "").strip()
        if not question:
            return render_template("_ai_answer.html", error="Enter a question first."), 400
        if len(question) > 500:
            return render_template(
                "_ai_answer.html", error="Keep your question under 500 characters."
            ), 400

        all_records = PlantReference.query.order_by(PlantReference.common_name).all()
        records = _records_for_question(question, all_records)
        plants = [record.to_dict() for record in records]
        try:
            result = app.extensions["almanac_ai"].ask(question, plants)
        except AIUnavailableError:
            return render_template(
                "_ai_answer.html",
                error="The local AI model is unavailable. Check that Ollama is running and try again.",
            ), 503

        plants_by_slug = {plant["slug"]: plant for plant in plants}
        sources = [plants_by_slug[slug] for slug in result["sources"] if slug in plants_by_slug]
        return render_template(
            "_ai_answer.html", answer=result["answer"], sources=sources, question=question
        )

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

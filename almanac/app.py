import os

from flask import Flask, jsonify, render_template
from sqlalchemy import text

from extensions import db
from models import PlantReference
from seed_data import seed_reference_data


BASE_DIR = os.path.abspath(os.path.dirname(__file__))


def create_app() -> Flask:
    app = Flask(__name__, template_folder="templates")
    app.config.from_mapping(
        SQLALCHEMY_DATABASE_URI=os.environ.get(
            "DATABASE_URL",
            "sqlite:///" + os.path.join(BASE_DIR, "instance", "almanac.db"),
        ),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        AUTH_PUBLIC_URL=os.environ.get("AUTH_PUBLIC_URL", "http://localhost:5001"),
    )

    db_uri = app.config["SQLALCHEMY_DATABASE_URI"]
    if db_uri.startswith("sqlite:///"):
        database_directory = os.path.dirname(db_uri.removeprefix("sqlite:///"))
        if database_directory:
            os.makedirs(database_directory, exist_ok=True)

    db.init_app(app)

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

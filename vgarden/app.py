import os

from dotenv import load_dotenv
from flask import Flask
from jinja2 import ChoiceLoader, FileSystemLoader
from werkzeug.middleware.proxy_fix import ProxyFix

load_dotenv()

from config import Config
from extensions import csrf, db


def create_app(config_class: type = Config) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config_class)
    # Behind the nginx proxy each service is mounted under a path prefix
    # (/vgarden, /auth, ...). Honour X-Forwarded-* so url_for() and redirects
    # carry that prefix. A no-op when the headers are absent (direct/local runs).
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
    here = os.path.abspath(os.path.dirname(__file__))
    app.jinja_loader = ChoiceLoader([
        app.jinja_loader,
        FileSystemLoader([
            os.path.join(here, "shared_templates"),
            os.path.join(here, "..", "shared", "templates"),
        ]),
    ])

    db_uri = app.config["SQLALCHEMY_DATABASE_URI"]
    if db_uri.startswith("sqlite:///"):
        os.makedirs(os.path.dirname(db_uri.removeprefix("sqlite:///")), exist_ok=True)

    db.init_app(app)
    csrf.init_app(app)

    from ai import OllamaGardenAI
    from containers import bp as containers_bp
    from garden_ai import bp as garden_ai_bp
    from garden_areas import bp as garden_areas_bp
    from plantings import bp as plantings_bp
    from routes import bp as gardens_bp
    from weather import OpenMeteoClient

    app.register_blueprint(gardens_bp)
    app.register_blueprint(garden_areas_bp)
    app.register_blueprint(containers_bp)
    app.register_blueprint(plantings_bp)
    app.register_blueprint(garden_ai_bp)

    app.extensions["garden_ai"] = OllamaGardenAI(
        base_url=app.config.get("OLLAMA_URL", "http://localhost:11434"),
        model=app.config.get("OLLAMA_MODEL", "qwen3:4b-instruct"),
        timeout=app.config.get("OLLAMA_TIMEOUT", 120),
        auto_pull=app.config.get("OLLAMA_AUTO_PULL", False),
    )
    app.extensions["weather"] = OpenMeteoClient(
        geocoding_url=app.config.get(
            "OPEN_METEO_GEOCODING_URL", "https://geocoding-api.open-meteo.com/v1/search"
        ),
        forecast_url=app.config.get(
            "OPEN_METEO_FORECAST_URL", "https://api.open-meteo.com/v1/forecast"
        ),
        timeout=app.config.get("WEATHER_TIMEOUT", 10),
        cache_ttl=app.config.get("WEATHER_CACHE_TTL", 1800),
    )

    @app.context_processor
    def inject_public_urls():
        return {
            "auth_public_url": app.config["AUTH_PUBLIC_URL"],
            "health_public_url": app.config.get(
                "HEALTH_PUBLIC_URL", "http://localhost:5003/plant-health-records/"
            ),
            "almanac_public_url": app.config.get(
                "ALMANAC_PUBLIC_URL", "http://localhost:5004/"
            ),
        }

    with app.app_context():
        db.create_all()

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

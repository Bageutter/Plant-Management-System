import os

from dotenv import load_dotenv
from flask import Flask
from jinja2 import ChoiceLoader, FileSystemLoader

load_dotenv()

from config import Config
from extensions import db


def create_app(config_class: type = Config) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config_class)
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

    from routes import bp as gardens_bp

    app.register_blueprint(gardens_bp)

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

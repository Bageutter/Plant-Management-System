import os

from dotenv import load_dotenv
from flask import Flask
from jinja2 import ChoiceLoader, FileSystemLoader

load_dotenv()

from config import Config
from extensions import csrf, db, login_manager


def create_app(config_class: type = Config) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config_class)
    app.jinja_loader = ChoiceLoader([
        app.jinja_loader,
        FileSystemLoader(os.path.join(os.path.abspath(os.path.dirname(__file__)), "shared_templates")),
    ])

    db_uri = app.config["SQLALCHEMY_DATABASE_URI"]
    if db_uri.startswith("sqlite:///"):
        os.makedirs(os.path.dirname(db_uri.removeprefix("sqlite:///")), exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    csrf.init_app(app)

    from models import User

    @login_manager.user_loader
    def load_user(user_id: str):
        return db.session.get(User, int(user_id))

    from routes import bp as auth_bp

    app.register_blueprint(auth_bp)

    @app.context_processor
    def inject_public_urls():
        return {
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

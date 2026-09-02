import os

from dotenv import load_dotenv
from flask import Flask
from jinja2 import ChoiceLoader, FileSystemLoader
from werkzeug.middleware.proxy_fix import ProxyFix

load_dotenv()

from config import Config
from extensions import csrf, db, login_manager


def create_app(config_class: type = Config) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config_class)
    # Behind the nginx proxy each service is mounted under a path prefix
    # (/auth, /vgarden, ...). Honour X-Forwarded-* so url_for() and redirects
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

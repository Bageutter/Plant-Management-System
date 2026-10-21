import os

from flask import Flask, render_template
from jinja2 import ChoiceLoader, FileSystemLoader
from werkzeug.middleware.proxy_fix import ProxyFix

app = Flask(__name__)
# Served at the proxy root; honour X-Forwarded-* for correct scheme/host.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
app.jinja_loader = ChoiceLoader([
    app.jinja_loader,
    FileSystemLoader(os.path.join(os.path.abspath(os.path.dirname(__file__)), "shared_templates")),
])

AUTH_URL = os.environ.get("AUTH_URL", "http://localhost:5001")
HEALTH_URL = os.environ.get("HEALTH_URL", "http://localhost:5003/plant-health-records/")
ALMANAC_URL = os.environ.get("ALMANAC_URL", "http://localhost:5004/")


@app.route("/")
def index():
    return render_template(
        "index.html",
        auth_url=AUTH_URL,
        health_url=HEALTH_URL,
        almanac_url=ALMANAC_URL,
    )


if __name__ == "__main__":
    # 0.0.0.0 inside the container only; compose exposes 5000 to the proxy, not the host.
    # Debug (auto-reload) stays on by default for local development; FLASK_DEBUG=false turns it off.
    app.run(host="0.0.0.0", debug=os.environ.get("FLASK_DEBUG", "true").lower() == "true")  # noqa: S104

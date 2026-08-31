import os

from flask import Flask, render_template
from jinja2 import ChoiceLoader, FileSystemLoader

app = Flask(__name__)
app.jinja_loader = ChoiceLoader([
    app.jinja_loader,
    FileSystemLoader(os.path.join(os.path.abspath(os.path.dirname(__file__)), "shared_templates")),
])

AUTH_URL = os.environ.get("AUTH_URL", "http://localhost:5001")


@app.route("/")
def index():
    return render_template("index.html", auth_url=AUTH_URL)


if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True)

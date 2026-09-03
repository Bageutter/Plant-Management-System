import os
import re
import sys
from datetime import datetime

from flask import (
    Flask,
    abort,
    current_app,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from jinja2 import ChoiceLoader, FileSystemLoader
from sqlalchemy import text
from werkzeug.middleware.proxy_fix import ProxyFix

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# The shared agentic-loop module (shared/ai_loop.py): mounted at /app/ai_loop.py
# in the container, ../shared/ai_loop.py for local/test runs.
_SHARED = os.path.join(BASE_DIR, "..", "shared")
if os.path.isdir(_SHARED) and _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)

from ai import AIUnavailableError, OllamaAlmanacAI, sources_for_text
from auth_client import AuthClient
from extensions import csrf, db
from models import AIChatMessage, AILoopRun, PlantingMonth, PlantReference
from seed_data import seed_reference_data

try:
    import ai_loop
except ImportError:  # bare image without shared/ai_loop.py mounted -> single-shot
    ai_loop = None

CHAT_HISTORY_LIMIT = 20


class _SingleShot:
    """Minimal LoopResult-alike for the bare-image path."""

    def __init__(self, answer):
        self.answer = answer
        self.iterations = 1
        self.verdict = "fallback"
        self.run_id = None
        self.transcript_path = ""
        self.trace = []


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


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _unique_slug(base: str) -> str:
    base = base or "plant"
    slug, n = base, 2
    while PlantReference.query.filter_by(slug=slug).first() is not None:
        slug = f"{base}-{n}"
        n += 1
    return slug


def _parse_plant_form(form) -> tuple[dict, list[int], str | None]:
    """Return (fields, month_numbers, error) from a create/edit form."""
    fields = {
        key: (form.get(key) or "").strip()
        for key in ("common_name", "scientific_name", "family", "summary")
    }
    if not fields["common_name"]:
        return fields, [], "Common name is required."
    if not fields["scientific_name"]:
        return fields, [], "Scientific name is required."

    months = []
    for raw in form.getlist("months"):
        try:
            month = int(raw)
        except (TypeError, ValueError):
            return fields, [], "Planting months must be numbers 1-12."
        if not 1 <= month <= 12:
            return fields, [], "Planting months must be between 1 and 12."
        months.append(month)
    return fields, sorted(set(months)), None


def _apply_plant(plant: PlantReference, fields: dict, months: list[int]) -> None:
    plant.common_name = fields["common_name"]
    plant.scientific_name = fields["scientific_name"]
    plant.family = fields["family"]
    plant.summary = fields["summary"]

    # Diff rather than replace: assigning a fresh list would try to INSERT a
    # month row before deleting the old one with the same (plant, month) and
    # trip the unique constraint mid-flush.
    wanted = set(months)
    existing = {m.month_number: m for m in plant.planting_months}
    for number, row in existing.items():
        if number not in wanted:
            plant.planting_months.remove(row)
    for number in sorted(wanted - existing.keys()):
        plant.planting_months.append(PlantingMonth(month_number=number))


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
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-almanac-secret-key-change-me"),
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
        # Agentic loop (Plan -> Act -> Observe -> Adapt); see docs/agentic-ai-workflow.md.
        OLLAMA_REVIEW_MODEL=os.environ.get("OLLAMA_REVIEW_MODEL", "llama3.1:8b"),
        AI_LOOP_MAX_ITERATIONS=int(os.environ.get("AI_LOOP_MAX_ITERATIONS", "2")),
        AI_LOOP_LOG_DIR=os.environ.get(
            "AI_LOOP_LOG_DIR", os.path.join(BASE_DIR, "..", "tools", "ai-loop", "logs")
        ),
    )
    if test_config:
        app.config.update(test_config)

    db_uri = app.config["SQLALCHEMY_DATABASE_URI"]
    if db_uri.startswith("sqlite:///"):
        database_directory = os.path.dirname(db_uri.removeprefix("sqlite:///"))
        if database_directory:
            os.makedirs(database_directory, exist_ok=True)

    db.init_app(app)
    csrf.init_app(app)
    app.extensions["auth_client"] = AuthClient(app.config["AUTH_URL"])
    app.extensions["almanac_ai"] = OllamaAlmanacAI(
        base_url=app.config["OLLAMA_URL"],
        model=app.config["OLLAMA_MODEL"],
        timeout=app.config["OLLAMA_TIMEOUT"],
        auto_pull=app.config.get("OLLAMA_AUTO_PULL", False),
    )
    app.extensions["ai_loop_reviewer"] = (
        ai_loop.build_reviewer(app.config) if ai_loop is not None else None
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

    # --- Plant reference CRUD (browser, login-gated) ---

    def _login_or_redirect():
        """Return the auth user, or a redirect response to the login page."""
        user = _current_auth_user()
        if user is None:
            return None, redirect(f"{app.config['AUTH_PUBLIC_URL']}/login")
        return user, None

    @app.get("/plants/new")
    def new_plant():
        _, bounce = _login_or_redirect()
        if bounce:
            return bounce
        return render_template("plant_form.html", plant=None, months=[], mode="new")

    @app.post("/plants")
    def create_plant():
        _, bounce = _login_or_redirect()
        if bounce:
            return bounce

        fields, months, error = _parse_plant_form(request.form)
        if error:
            flash(error, "error")
            return render_template(
                "plant_form.html", plant=None, months=months, mode="new", fields=fields
            ), 400

        plant = PlantReference(slug=_unique_slug(_slugify(fields["common_name"])))
        _apply_plant(plant, fields, months)
        db.session.add(plant)
        db.session.commit()
        flash(f'Added "{plant.common_name}".', "success")
        return redirect(url_for("plant_detail", slug=plant.slug))

    @app.get("/plants/<slug>/edit")
    def edit_plant(slug: str):
        _, bounce = _login_or_redirect()
        if bounce:
            return bounce
        plant = PlantReference.query.filter_by(slug=slug).first()
        if plant is None:
            return render_template("404.html"), 404
        months = [m.month_number for m in plant.planting_months]
        return render_template("plant_form.html", plant=plant, months=months, mode="edit")

    @app.post("/plants/<slug>/edit")
    def update_plant(slug: str):
        _, bounce = _login_or_redirect()
        if bounce:
            return bounce
        plant = PlantReference.query.filter_by(slug=slug).first()
        if plant is None:
            return render_template("404.html"), 404

        fields, months, error = _parse_plant_form(request.form)
        if error:
            flash(error, "error")
            return render_template(
                "plant_form.html", plant=plant, months=months, mode="edit", fields=fields
            ), 400

        _apply_plant(plant, fields, months)
        db.session.commit()
        flash("Saved.", "success")
        return redirect(url_for("plant_detail", slug=plant.slug))

    @app.post("/plants/<slug>/delete")
    def delete_plant(slug: str):
        _, bounce = _login_or_redirect()
        if bounce:
            return bounce
        plant = PlantReference.query.filter_by(slug=slug).first()
        if plant is None:
            return render_template("404.html"), 404
        name = plant.common_name
        db.session.delete(plant)
        db.session.commit()
        flash(f'Deleted "{name}".', "success")
        return redirect(url_for("index"))

    # --- Plant reference API ---

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

    def _api_user_or_401():
        return _current_auth_user()

    def _api_parse(payload: dict):
        class _Form:
            def get(self, key):
                return payload.get(key)

            def getlist(self, key):
                value = payload.get(key, [])
                return value if isinstance(value, list) else [value]

        return _parse_plant_form(_Form())

    @app.post("/api/plants")
    @csrf.exempt
    def api_create_plant():
        if _api_user_or_401() is None:
            return jsonify({"error": "login required"}), 401
        fields, months, error = _api_parse(request.get_json(silent=True) or {})
        if error:
            return jsonify({"error": error}), 400
        plant = PlantReference(slug=_unique_slug(_slugify(fields["common_name"])))
        _apply_plant(plant, fields, months)
        db.session.add(plant)
        db.session.commit()
        return jsonify(plant.to_dict()), 201

    @app.route("/api/plants/<slug>", methods=["PUT", "PATCH"])
    @csrf.exempt
    def api_update_plant(slug: str):
        if _api_user_or_401() is None:
            return jsonify({"error": "login required"}), 401
        plant = PlantReference.query.filter_by(slug=slug).first()
        if plant is None:
            return jsonify({"error": "plant reference not found"}), 404
        fields, months, error = _api_parse(request.get_json(silent=True) or {})
        if error:
            return jsonify({"error": error}), 400
        _apply_plant(plant, fields, months)
        db.session.commit()
        return jsonify(plant.to_dict())

    @app.delete("/api/plants/<slug>")
    @csrf.exempt
    def api_delete_plant(slug: str):
        if _api_user_or_401() is None:
            return jsonify({"error": "login required"}), 401
        plant = PlantReference.query.filter_by(slug=slug).first()
        if plant is None:
            return jsonify({"error": "plant reference not found"}), 404
        db.session.delete(plant)
        db.session.commit()
        return "", 204

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
        history = [{"role": m.role, "content": m.content} for m in _chat_history(owner_key)]

        def build_context():
            grounding = {
                "current_month": datetime.now().strftime("%B"),
                "plant_records": plants,
                "conversation": history,
            }
            plan_summary = {
                "plant_records": len(plants),
                "of_total": len(all_records),
                "history_messages": len(history),
            }
            return grounding, plan_summary

        ai_client = app.extensions["almanac_ai"]
        try:
            if ai_loop is None:
                grounding, _ = build_context()
                result = _SingleShot(ai_client.draft(question, grounding, None))
            else:
                loop = ai_loop.AgenticLoop(
                    service="almanac",
                    drafter=lambda q, g, fb: ai_client.draft(q, g, fb),
                    reviewer=app.extensions.get("ai_loop_reviewer"),
                    log_dir=app.config["AI_LOOP_LOG_DIR"],
                    max_iterations=app.config["AI_LOOP_MAX_ITERATIONS"],
                )
                result = loop.run(question, build_context)
        except AIUnavailableError:
            return _render_chat(
                owner_key,
                "The local AI model is unavailable. Check that Ollama is running and try again.",
            ), 503

        user_msg = AIChatMessage(owner_key=owner_key, role="user", content=question)
        assistant_msg = AIChatMessage(
            owner_key=owner_key,
            role="assistant",
            content=result.answer,
            source_slugs=sources_for_text(result.answer, plants),
        )
        db.session.add_all([user_msg, assistant_msg])
        db.session.flush()
        if result.run_id:
            db.session.add(
                AILoopRun(
                    owner_key=owner_key,
                    message_id=assistant_msg.id,
                    run_id=result.run_id,
                    question=question,
                    final_answer=result.answer,
                    iterations=result.iterations,
                    verdict=result.verdict,
                    transcript_path=result.transcript_path,
                    trace=result.trace,
                )
            )
        db.session.commit()
        return _render_chat(owner_key)

    @app.get("/ai/loop/<int:run_id>")
    def ai_loop_trace(run_id: int):
        owner_key = _chat_owner_key()
        run = db.session.get(AILoopRun, run_id)
        if owner_key is None or run is None or run.owner_key != owner_key:
            abort(404)
        return render_template("loop_trace.html", run=run)

    @app.post("/ai/clear")
    def clear_ai_chat():
        owner_key = _chat_owner_key()
        if owner_key is None:
            return _render_chat(None, "Your session has expired. Log in again to use the chat."), 401
        AILoopRun.query.filter_by(owner_key=owner_key).delete()
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

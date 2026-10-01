"""Virtual Garden UI access to the shared local MCP and RAG servers (Release 1).

Every route here is scoped to one owned garden: `require_login` + `_get_owned_garden`
(404 for a stranger, same as the rest of vgarden's owner-scoped routes). Garden
data is private per-owner — unlike the Almanac catalogue or Plant Health
assessments, which are public — so, unlike those features' equivalent routes,
these also keep normal CSRF protection (the forms carry a csrf_token, same as
the existing "ask about this garden" chat in garden_ai.py).
"""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify, render_template, request

from auth_utils import require_garden_owner, require_login
from extensions import db
from integrations import GARDEN_TOOLS, IntegrationDisabled, IntegrationUnavailable
from models import Garden

bp = Blueprint("garden_integrations", __name__)

MAX_QUESTION_CHARS = 500


def _get_owned_garden(garden_id: int) -> Garden:
    garden = db.session.get(Garden, garden_id)
    require_garden_owner(garden)
    return garden


def _mcp():
    return current_app.extensions["mcp"]


def _rag():
    return current_app.extensions["rag"]


def _wants_html() -> bool:
    if request.headers.get("HX-Request") == "true":
        return True
    accept = request.accept_mimetypes
    if not accept.provided:
        return False
    return accept["text/html"] > accept["application/json"]


def _integration_error(exc: Exception, wants_html: bool, *, fragment: str = "_error.html"):
    """Map integration failures to honest status codes: 400 input, 503 disabled,
    502 shared server unreachable / failed."""

    if isinstance(exc, ValueError):
        code = 400
    elif isinstance(exc, IntegrationDisabled):
        code = 503
    else:
        code = 502
    if wants_html:
        return render_template(fragment, message=str(exc), error=True, code=code), code
    return jsonify({"error": str(exc), "status_code": code}), code


@bp.route("/integrations")
def service_integrations_status():
    """Service-wide wiring status: whether MCP/RAG are enabled and where they
    point. No owner data here (unlike the per-garden route below), so this needs
    no login - it mirrors health's equivalent and is what the compose smoke test
    (scripts/test/smoke-vgarden.sh) uses to confirm MCP_ENABLED/RAG_ENABLED
    without a logged-in session. It does not probe reachability, only config."""

    mcp, rag = _mcp(), _rag()
    return jsonify(
        {
            "mcp": {"enabled": mcp.enabled, "url": mcp.url},
            "rag": {"enabled": rag.enabled, "url": rag.base_url},
        }
    )


@bp.route("/gardens/<int:garden_id>/integrations")
@require_login
def integrations_status(garden_id):
    """Wiring status of both integrations for this garden. Probes only when a
    mode is enabled, so a CI smoke test (both disabled) proves configuration
    without any network."""

    _get_owned_garden(garden_id)

    def probe(client, fn):
        if not client.enabled:
            return None
        try:
            fn()
            return True
        except (IntegrationUnavailable, IntegrationDisabled):
            return False

    mcp, rag = _mcp(), _rag()
    return jsonify(
        {
            "mcp": {"enabled": mcp.enabled, "url": mcp.url, "reachable": probe(mcp, mcp.list_tools)},
            "rag": {"enabled": rag.enabled, "url": rag.base_url, "reachable": probe(rag, rag.status)},
        }
    )


@bp.route("/gardens/<int:garden_id>/tools")
@require_login
def list_tools(garden_id):
    """Tools registered on the shared MCP server (all features), flagged for ours."""

    _get_owned_garden(garden_id)
    try:
        return jsonify(_mcp().list_tools())
    except (IntegrationDisabled, IntegrationUnavailable) as exc:
        return _integration_error(exc, False)


@bp.route("/gardens/<int:garden_id>/tools/run", methods=["POST"])
@require_login
def run_tool(garden_id):
    """Run one whitelisted, read-only Virtual Garden tool scoped to this garden.

    Only a ``tool`` name is accepted from the request body — ``garden_id`` is
    always the one from the authenticated URL, never a client-supplied
    argument, so this garden's owner can never point a tool call at someone
    else's garden.
    """

    garden = _get_owned_garden(garden_id)
    wants_html = _wants_html()
    source = request.get_json(silent=True) or {} if request.is_json else request.form
    tool = (source.get("tool") or "").strip()
    try:
        if tool not in GARDEN_TOOLS:
            raise ValueError(f"Provide one of: {', '.join(GARDEN_TOOLS)}.")
        result = _mcp().call(tool, garden.id)
    except (ValueError, IntegrationDisabled, IntegrationUnavailable) as exc:
        return _integration_error(exc, wants_html)

    if wants_html:
        return render_template("_mcp_result.html", result=result)
    return jsonify(result)


@bp.route("/gardens/<int:garden_id>/ask", methods=["POST"])
@require_login
def ask_garden(garden_id):
    """Ask the shared RAG server a question grounded only in this garden's state."""

    garden = _get_owned_garden(garden_id)
    wants_html = _wants_html()
    source = request.get_json(silent=True) or {} if request.is_json else request.form
    try:
        question = (source.get("question") or "").strip()
        if not question:
            raise ValueError("Provide a question.")
        if len(question) > MAX_QUESTION_CHARS:
            raise ValueError(f"question must be {MAX_QUESTION_CHARS} characters or fewer.")
        answer = _rag().ask(question, garden_id=garden.id)
    except (ValueError, IntegrationDisabled, IntegrationUnavailable) as exc:
        return _integration_error(exc, wants_html)

    if wants_html:
        return render_template("_rag_answer.html", answer=answer)
    return jsonify(answer)


@bp.route("/gardens/<int:garden_id>/ask/sync", methods=["POST"])
@require_login
def sync_garden_index(garden_id):
    """Ask the shared RAG server to (re)index every garden's current state."""

    _get_owned_garden(garden_id)
    wants_html = _wants_html()
    try:
        result = _rag().sync_vgarden()
    except (IntegrationDisabled, IntegrationUnavailable) as exc:
        return _integration_error(exc, wants_html, fragment="_notice.html")

    if wants_html:
        message = (
            f"Indexed {result.get('documents', 0)} garden(s) as {result.get('chunks', 0)} passages"
            + (" with embeddings." if result.get("embedded") else ".")
        )
        return render_template("_notice.html", message=message, error=False, code=200)
    return jsonify(result)

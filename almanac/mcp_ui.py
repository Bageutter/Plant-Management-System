"""Explicit user-selected MCP calls with visible evidence; no automatic inference."""

from flask import Blueprint, current_app, render_template, request

from mcp_evidence import BOUNDARIES, run_tool


mcp_ui = Blueprint("mcp_ui", __name__, url_prefix="/tools")


@mcp_ui.get("")
def index():
    return render_template("mcp_tools.html", enabled=current_app.config["MCP_ENABLED"])


@mcp_ui.post("/run")
def run():
    if not current_app.config["MCP_ENABLED"] or request.form.get("enabled") != "on":
        return render_template(
            "_mcp_result.html", error="Tool mode is off. Enable it to run a lookup."
        ), 403
    tool = request.form.get("tool", "")
    if tool not in BOUNDARIES:
        return render_template(
            "_mcp_result.html", error="Choose one of the three available tools."
        ), 400
    try:
        if tool == "search_catalogue":
            arguments = {
                "query": request.form.get("query", ""),
                "kind": request.form.get("kind", "all"),
            }
        elif tool == "get_plant":
            arguments = {"slug": request.form.get("slug", "")}
        elif tool == "get_problem":
            arguments = {
                "kind": request.form.get("problem_kind", "pest"),
                "record_id": int(request.form.get("record_id", "")),
            }
        evidence = run_tool(current_app.config["MCP_ALMANAC_BASE_URL"], tool, arguments)
    except (ValueError, TypeError):
        return render_template(
            "_mcp_result.html",
            error="Check the tool inputs; use a catalogue key and valid numbers.",
        ), 400
    except Exception:
        current_app.logger.warning("MCP explorer could not connect to its configured adapter")
        return render_template(
            "_mcp_result.html", error="The tool connection is unavailable. Please try again later."
        ), 503
    call = evidence["calls"][-1]
    return render_template(
        "_mcp_result.html",
        evidence=evidence,
        call=call,
        output=call["output"],
        boundary=BOUNDARIES[tool],
    ), 502 if call["is_error"] else 200

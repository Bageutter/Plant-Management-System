"""Connect feature backends (and the terminal) to this Multi-Agent Server.

A feature hands over a task plus the evidence it has already selected, the server
runs Planner -> Worker -> Reviewer, and the result waits for a human decision. This
module is the one place that knows the server's HTTP contract, so a backend (or a
terminal script) can call ``submit_task`` and ``review_task`` instead of hand-writing
requests. It uses only the standard library, so it can be copied into any service.

Terminal use, from this folder, with the server running on :8003::

    python application_integration.py health "Summarise this plant's assessments" evidence.json
    python application_integration.py almanac "Tomato sun needs"            # Worker retrieves via MCP
    python application_integration.py --review <workflow_id> accept "Checked" --reviewer guhan-terminal

``evidence.json`` holds ``{"mode": ..., "passages": [{chunk_id, title, text}, ...]}``
(1-10 passages). Almanac tasks may omit it; vgarden and health tasks must supply it,
because this server never reads those features' data itself.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

FEATURES = ("almanac", "vgarden", "health")
EVIDENCE_REQUIRED = ("vgarden", "health")
DECISIONS = ("accept", "partially_accept", "request_changes", "reject")
DEFAULT_URL = "http://127.0.0.1:8003"
RUN_TIMEOUT = 900  # three local model calls


class ServerError(RuntimeError):
    """The server refused the request or could not be reached."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def server_url(base_url: str | None = None) -> str:
    url = (base_url or os.environ.get("MULTI_AGENT_URL", DEFAULT_URL)).rstrip("/")
    if not url.startswith(("http://", "https://")):
        raise ValueError("MULTI_AGENT_URL must be an http(s) URL")
    return url


def http_request(method: str, path: str, payload: dict | None = None, *,
                 base_url: str | None = None, timeout: float = 15) -> tuple[int, dict]:
    """One JSON request to the server: ``(status, body)``. Raises ServerError when
    the server cannot be reached or answers something other than JSON."""

    url = f"{server_url(base_url)}{path}"
    data = json.dumps(payload).encode() if payload is not None else None
    request = Request(url, data=data, method=method,  # noqa: S310 -- http(s) checked in server_url
                      headers={"Content-Type": "application/json"} if data else {})
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 -- http(s) only
            return response.status, json.load(response)
    except HTTPError as error:
        try:
            body = json.load(error)
        except ValueError:
            body = {"error": f"The Multi-Agent Server answered HTTP {error.code}."}
        return error.code, body
    except (URLError, TimeoutError, OSError) as error:
        raise ServerError(
            "The shared Multi-Agent Server could not be reached. Start it with "
            "`python ai-services/multi-agent-server/app.py` and try again."
        ) from error
    except ValueError as error:
        raise ServerError("The Multi-Agent Server returned an unexpected response.") from error


def _expect(status: int, body: dict, ok: int) -> dict:
    if status != ok or not isinstance(body, dict):
        message = body.get("error") if isinstance(body, dict) else None
        raise ServerError(message or f"The Multi-Agent Server answered HTTP {status}.", status)
    return body


def submit_task(feature: str, task: str, evidence: dict | None = None, *, run: bool = True,
                base_url: str | None = None, timeout: float = RUN_TIMEOUT, request=None) -> dict:
    """Send a feature's task (and its evidence) to the server and, by default, run
    Planner -> Worker -> Reviewer straight away.

    Returns the workflow state: ``workflow_id``, ``status`` (``awaiting_human_review``
    after a run, ``received`` with ``run=False``) and, after a run, ``plan``,
    ``evidence``, ``result``, ``review`` and ``history``. The caller then collects the
    human decision with :func:`review_task`.

    ``request`` lets a test (or an in-process caller) supply its own
    ``(method, path, payload) -> (status, body)`` transport.
    """

    if feature not in FEATURES:
        raise ValueError(f"feature must be one of: {', '.join(FEATURES)}")
    if not isinstance(task, str) or not 1 <= len(task.strip()) <= 500:
        raise ValueError("task must be 1 to 500 characters")
    if evidence is None and feature in EVIDENCE_REQUIRED:
        raise ValueError(f"{feature} tasks must include the feature's evidence")
    if evidence is not None and (not isinstance(evidence, dict)
                                 or not isinstance(evidence.get("passages"), list)):
        raise ValueError("evidence must be {'mode': ..., 'passages': [...]}")

    def default_request(method, path, payload, *, timeout=15):
        return http_request(method, path, payload, base_url=base_url, timeout=timeout)

    send = request or default_request
    body = {"task": task.strip(), "source": feature}
    if evidence is not None:
        body["evidence"] = evidence
    created = _expect(*send("POST", "/workflow", body), 201)
    if not run:
        return created
    try:
        return _expect(*send("POST", "/workflow/run", {"workflow_id": created["workflow_id"]},
                             timeout=timeout), 200)
    except TypeError:
        # A transport without a timeout parameter.
        return _expect(*send("POST", "/workflow/run", {"workflow_id": created["workflow_id"]}), 200)


def workflow_status(workflow_id: str, *, base_url: str | None = None, request=None) -> dict:
    send = request or (lambda m, p, payload=None: http_request(m, p, payload, base_url=base_url))
    return _expect(*send("GET", f"/workflow/status?id={workflow_id}", None), 200)


def review_task(workflow_id: str, decision: str, feedback: str = "", *,
                reviewer_id: str = "terminal", base_url: str | None = None, request=None) -> dict:
    """Record the human decision; ``request_changes`` needs feedback and lets the
    workflow run again with it."""

    if decision not in DECISIONS:
        raise ValueError(f"decision must be one of: {', '.join(DECISIONS)}")
    send = request or (lambda m, p, payload=None: http_request(m, p, payload, base_url=base_url))
    body = {"workflow_id": workflow_id, "decision": decision, "feedback": feedback,
            "reviewer_id": reviewer_id}
    return _expect(*send("POST", "/workflow/review", body), 200)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("feature", nargs="?", choices=FEATURES)
    parser.add_argument("task", nargs="?")
    parser.add_argument("evidence", nargs="?", help="JSON file with mode and passages")
    parser.add_argument("--url", help=f"server URL (default $MULTI_AGENT_URL or {DEFAULT_URL})")
    parser.add_argument("--no-run", action="store_true", help="create the workflow without running it")
    parser.add_argument("--review", nargs="+", metavar=("WORKFLOW_ID DECISION", "FEEDBACK"),
                        help="record a human decision instead of submitting a task")
    parser.add_argument("--reviewer", default="terminal")
    args = parser.parse_args(argv)
    try:
        if args.review:
            if len(args.review) < 2:
                parser.error("--review needs WORKFLOW_ID DECISION [FEEDBACK]")
            state = review_task(args.review[0], args.review[1], " ".join(args.review[2:]),
                                reviewer_id=args.reviewer, base_url=args.url)
        else:
            if not args.feature or not args.task:
                parser.error("feature and task are required")
            evidence = None
            if args.evidence:
                with open(args.evidence, encoding="utf-8") as handle:
                    evidence = json.load(handle)
            state = submit_task(args.feature, args.task, evidence, run=not args.no_run, base_url=args.url)
    except (ValueError, ServerError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(json.dumps(state, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Validate shared MCP or RAG through a running feature backend, without writes.

Two features are supported (``--feature``):

- ``almanac`` (default, unchanged): read-only catalogue search / grounded Q&A
  against public, unauthenticated Almanac endpoints.
- ``vgarden``: Virtual Garden's data is private per-owner, so there is no public
  endpoint to call anonymously. ``VgardenSession`` bootstraps a throwaway account
  through the *real* browser-facing flow (register -> create a garden -> the SSO
  handoff into vgarden -> seed one area and planting) before running the same
  MCP/RAG checks against vgarden's owner-scoped routes, with that session's
  cookie and CSRF token. The seeded account is never deleted; it's harmless
  throwaway data, the same way the Almanac checks run against the live catalogue.
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import logging
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib import error, parse, request
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
MAX_ATTEMPTS = 2
HTTP_TIMEOUT = 190  # Allow the backend's 180-second local model request to finish.
sys.path.insert(0, str(ROOT / "shared"))
from ai_loop import LoopLogger  # noqa: E402 -- reuse the project's native logger

CSRF_FIELD_RE = re.compile(r"<input[^>]*csrf_token[^>]*>")
VALUE_ATTR_RE = re.compile(r'value="([^"]*)"')
OPEN_GARDEN_RE = re.compile(r"/gardens/(\d+)/open")


def post_json(url: str, payload: dict, timeout: int, *, opener=None, headers=None) -> dict:
    req = request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json", **(headers or {})},
        method="POST",
    )
    opened = opener.open(req, timeout=timeout) if opener else request.urlopen(req, timeout=timeout)
    with opened as response:
        body = json.load(response)
    if not isinstance(body, dict):
        raise ValueError("The backend response must be a JSON object.")
    return body


# --------------------------------------------------------------------------- #
# Almanac — public, unauthenticated contract                                  #
# --------------------------------------------------------------------------- #


def check_mcp(body: dict, payload: dict) -> list[str]:
    issues = []
    if body.get("tool") != payload["tool"] or body.get("is_error") is not False:
        issues.append("The requested MCP tool did not return a successful result.")
    page = body.get("structured_content")
    if not isinstance(page, dict) or not isinstance(page.get("items"), list):
        return issues + ["MCP must return structured_content with an items list."]
    items = page["items"]
    if not items or len(items) > payload["limit"]:
        issues.append("The seeded search must return between 1 and the requested limit of records.")
    for item in items:
        if not isinstance(item, dict):
            issues.append("Every search result must be a structured record.")
            continue
        for key in ("key", "name", "uri", "path"):
            if not isinstance(item.get(key), str) or not item[key].strip():
                issues.append(f"A search result is missing its {key} reference.")
        if type(item.get("id")) is not int or item["id"] < 1:
            issues.append("A search result must have a positive integer id.")
        if payload["query"].lower() not in str(item.get("name", "")).lower():
            issues.append("A returned record does not match the requested catalogue name.")
        if item.get("kind") not in ("plant", "pest", "disease"):
            issues.append("A search result has an unknown record kind.")
        elif payload["kind"] != "all" and item["kind"] != payload["kind"]:
            issues.append("The search did not respect the requested record kind.")
    return list(dict.fromkeys(issues))


def check_rag(body: dict, *, refuse: bool) -> list[str]:
    issues = []
    if refuse:
        if body.get("insufficient_context") is not True:
            issues.append("The unrelated question must report insufficient context.")
        if body.get("confidence") != "insufficient":
            issues.append("A refusal must have insufficient confidence.")
        if body.get("answer") not in (None, "") or body.get("citations") != []:
            issues.append("A refusal must not invent an answer or cite unrelated records.")
        return issues
    if body.get("insufficient_context") is not False:
        issues.append("The seeded disease question did not produce a grounded answer.")
    if not isinstance(body.get("answer"), str) or not body["answer"].strip():
        issues.append("The grounded answer must contain text.")
    if body.get("confidence") not in ("low", "medium", "high"):
        issues.append("The answer must report a valid confidence category.")
    citations = body.get("citations")
    if not isinstance(citations, list) or not citations:
        return issues + ["The answer must cite at least one Almanac passage."]
    for citation in citations:
        if not isinstance(citation, dict):
            issues.append("Each citation must be a structured record.")
            continue
        if citation.get("source") != "almanac":
            issues.append("The answer cited a source outside the Almanac.")
        for key in ("chunk_id", "source_id", "title", "url", "excerpt"):
            if not str(citation.get(key) or "").strip():
                issues.append(f"A citation is missing its {key}.")
    return list(dict.fromkeys(issues))


class AlmanacBackend:
    """Public, unauthenticated calls straight to the Almanac integration routes."""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def setup(self) -> dict:
        return {"auth": "none (public Almanac endpoints)"}

    def cases(self, mode: str) -> list[dict]:
        if mode == "mcp":
            return [
                {
                    "name": name,
                    "path": "/integrations/mcp",
                    "payload": {"tool": "search_almanac_catalogue", "query": query, "kind": kind, "limit": 5},
                }
                for name, query, kind in (
                    ("plant_search", "tomato", "all"),
                    ("disease_search", "powdery mildew", "disease"),
                )
            ]
        return [
            {
                "name": "grounded_answer",
                "path": "/integrations/rag",
                "payload": {"question": "What helps prevent powdery mildew?"},
            },
            {
                "name": "unrelated_refusal",
                "path": "/integrations/rag",
                "payload": {"question": "Who won the 1986 FIFA World Cup?"},
            },
        ]

    def check(self, mode: str, name: str, body: dict, payload: dict) -> list[str]:
        return check_mcp(body, payload) if mode == "mcp" else check_rag(body, refuse=name == "unrelated_refusal")

    def post(self, path: str, payload: dict, timeout: int) -> dict:
        return post_json(self.base_url + path, payload, timeout)


# --------------------------------------------------------------------------- #
# Virtual Garden — private per-owner; bootstraps a real session first         #
# --------------------------------------------------------------------------- #


def check_vgarden_mcp(body: dict, payload: dict) -> list[str]:
    issues = []
    if body.get("tool") != payload["tool"] or body.get("is_error") is not False:
        return issues + ["The requested Virtual Garden MCP tool did not return a successful result."]
    data = body.get("structured_content")
    if not isinstance(data, dict):
        return issues + ["MCP must return structured_content as an object."]
    plantings = data.get("plantings") if payload["tool"] == "get_garden_snapshot" else data.get("items")
    if not isinstance(plantings, list) or not plantings:
        issues.append("The seeded garden must have at least one planting in the result.")
    elif not any(p.get("crop_name") == "Tomato" for p in plantings if isinstance(p, dict)):
        issues.append("The result did not include the seeded Tomato planting.")
    if payload["tool"] == "get_garden_snapshot" and data.get("garden_id") != payload["garden_id"]:
        issues.append("The snapshot returned the wrong garden.")
    return list(dict.fromkeys(issues))


def check_vgarden_rag(body: dict, *, refuse: bool, garden_id: int) -> list[str]:
    issues = []
    if refuse:
        if body.get("insufficient_context") is not True:
            issues.append("The unrelated question must report insufficient context.")
        if body.get("confidence") != "insufficient":
            issues.append("A refusal must have insufficient confidence.")
        if body.get("answer") not in (None, "") or body.get("citations") != []:
            issues.append("A refusal must not invent an answer or cite unrelated records.")
        return issues
    if body.get("insufficient_context") is not False:
        issues.append("The seeded planting question did not produce a grounded answer.")
    if not isinstance(body.get("answer"), str) or not body["answer"].strip():
        issues.append("The grounded answer must contain text.")
    if body.get("confidence") not in ("low", "medium", "high"):
        issues.append("The answer must report a valid confidence category.")
    citations = body.get("citations")
    if not isinstance(citations, list) or not citations:
        return issues + ["The answer must cite at least one of this garden's own passages."]
    for citation in citations:
        if not isinstance(citation, dict):
            issues.append("Each citation must be a structured record.")
            continue
        if citation.get("source") != "vgarden":
            issues.append("The answer cited a source outside Virtual Garden.")
        if citation.get("source_id") != str(garden_id):
            issues.append(
                "The answer cited a different garden's record — this is exactly the "
                "cross-garden leak the source_id scoping exists to prevent."
            )
        for key in ("chunk_id", "source_id", "title", "excerpt"):
            if not str(citation.get(key) or "").strip():
                issues.append(f"A citation is missing its {key}.")
    return list(dict.fromkeys(issues))


class VgardenSession:
    """Logs a throwaway account in through the real browser-facing flow — register,
    create a garden, follow the SSO handoff into vgarden, seed one area and
    planting — so validation exercises owner-scoped routes exactly as a browser
    would. No shortcuts: no direct DB access, no server-to-server token use."""

    def __init__(self, auth_base_url: str, vgarden_base_url: str, timeout: int):
        self.auth_base_url = auth_base_url.rstrip("/")
        self.vgarden_base_url = vgarden_base_url.rstrip("/")
        self.timeout = timeout
        self.opener = request.build_opener(request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.garden_id: int | None = None
        self.csrf_token: str | None = None
        self.email: str | None = None
        self.garden_name: str | None = None

    def _get(self, url: str) -> str:
        with self.opener.open(url, timeout=self.timeout) as response:
            return response.read().decode("utf-8")

    def _post_form(self, url: str, fields: dict) -> str:
        req = request.Request(url, data=parse.urlencode(fields).encode(), method="POST")
        with self.opener.open(req, timeout=self.timeout) as response:
            return response.read().decode("utf-8")

    @staticmethod
    def _csrf(html: str) -> str:
        field = CSRF_FIELD_RE.search(html)
        if not field:
            raise RuntimeError("Could not find a csrf_token field on the page.")
        value = VALUE_ATTR_RE.search(field.group(0))
        if not value:
            raise RuntimeError("The csrf_token field has no value attribute.")
        return value.group(1)

    def bootstrap(self) -> dict:
        suffix = uuid.uuid4().hex[:10]
        # auth's RegisterForm uses WTForms' Email() validator (email_validator), which
        # checks the domain actually accepts mail and specifically rejects RFC 2606
        # reserved domains (example.com/.test/...). mailinator.com is a real,
        # publicly documented disposable-inbox domain, so this passes that check
        # without sending anything to a real person. Requires outbound DNS, same as
        # a real signup through this app.
        self.email = f"vgarden-validate-{suffix}@mailinator.com"
        password = f"Validate-{suffix}!"
        self.garden_name = f"Validation garden {suffix}"

        register_html = self._get(f"{self.auth_base_url}/register")
        self._post_form(f"{self.auth_base_url}/register", {
            "csrf_token": self._csrf(register_html),
            "email": self.email, "password": password, "confirm_password": password,
        })

        account_html = self._get(f"{self.auth_base_url}/account")
        self._post_form(f"{self.auth_base_url}/gardens", {
            "csrf_token": self._csrf(account_html), "name": self.garden_name,
        })

        account_html = self._get(f"{self.auth_base_url}/account")
        match = OPEN_GARDEN_RE.search(account_html)
        if not match:
            raise RuntimeError("The created garden did not appear on the account page.")
        self.garden_id = int(match.group(1))

        # Follow the real SSO handoff (urllib resolves the relative post-login
        # redirect against the previous response, the same way a browser would).
        garden_html = self._get(f"{self.auth_base_url}/gardens/{self.garden_id}/open")
        self.csrf_token = self._csrf(garden_html)

        self._post_form(f"{self.vgarden_base_url}/gardens/{self.garden_id}/areas", {
            "csrf_token": self.csrf_token, "name": "Validation bed", "area_type": "bed",
            "pos_x": "0", "pos_y": "0", "width": "1", "length": "1",
        })
        garden_html = self._get(f"{self.vgarden_base_url}/gardens/{self.garden_id}/view")
        area_match = re.search(rf"/gardens/{self.garden_id}/areas/(\d+)", garden_html)
        if not area_match:
            raise RuntimeError("The seeded garden area did not appear on the garden page.")
        area_id = int(area_match.group(1))

        self._post_form(f"{self.vgarden_base_url}/gardens/{self.garden_id}/plantings", {
            "csrf_token": self.csrf_token, "crop_name": "Tomato", "quantity": "3",
            "lifecycle_state": "growing", "garden_area_id": str(area_id), "pos_x": "0", "pos_y": "0",
        })

        return {
            "email": self.email, "garden_id": self.garden_id, "garden_name": self.garden_name,
            "seeded": ["1 garden area", "1 planting (Tomato)"],
        }

    def sync_rag_index(self) -> None:
        self._post_form(f"{self.vgarden_base_url}/gardens/{self.garden_id}/ask/sync", {
            "csrf_token": self.csrf_token,
        })


class VgardenBackend:
    def __init__(self, auth_base_url: str, vgarden_base_url: str, timeout: int):
        self.session = VgardenSession(auth_base_url, vgarden_base_url, timeout)
        self.vgarden_base_url = vgarden_base_url.rstrip("/")

    def setup(self) -> dict:
        info = self.session.bootstrap()
        self.session.sync_rag_index()
        info["synced_rag_index"] = True
        return info

    def cases(self, mode: str) -> list[dict]:
        gid = self.session.garden_id
        if mode == "mcp":
            return [
                {
                    "name": name, "path": f"/gardens/{gid}/tools/run",
                    "payload": {"tool": tool, "garden_id": gid},
                }
                for name, tool in (
                    ("garden_snapshot", "get_garden_snapshot"),
                    ("garden_plantings", "list_garden_plantings"),
                )
            ]
        return [
            {
                "name": "grounded_answer", "path": f"/gardens/{gid}/ask",
                "payload": {"question": "What is growing in this garden?"},
            },
            {
                "name": "unrelated_refusal", "path": f"/gardens/{gid}/ask",
                "payload": {"question": "Who won the 1986 FIFA World Cup?"},
            },
        ]

    def check(self, mode: str, name: str, body: dict, payload: dict) -> list[str]:
        if mode == "mcp":
            return check_vgarden_mcp(body, payload)
        return check_vgarden_rag(body, refuse=name == "unrelated_refusal", garden_id=self.session.garden_id)

    def post(self, path: str, payload: dict, timeout: int) -> dict:
        return post_json(
            self.vgarden_base_url + path, payload, timeout,
            opener=self.session.opener, headers={"X-CSRFToken": self.session.csrf_token},
        )


def build_backend(args: argparse.Namespace):
    if args.feature == "almanac":
        return AlmanacBackend(args.base_url)
    return VgardenBackend(args.auth_base_url, args.base_url, HTTP_TIMEOUT)


def run(args: argparse.Namespace) -> dict:
    run_id = f"validate-{args.feature}-{args.mode}-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}"
    logger = LoopLogger(
        args.feature, str(getattr(args, "log_dir", None) or ROOT / "tools" / "ai-loop" / "logs"), run_id,
        f"Validate {args.feature} {args.mode} integration",
    )
    backend = build_backend(args)
    setup_info = backend.setup()
    pending = backend.cases(args.mode)
    results = {}
    logger.phase("plan", {
        "feature": args.feature,
        "mode": args.mode,
        "base_url": args.base_url,
        "setup": setup_info,
        "checks": [case["name"] for case in pending],
        "max_attempts": MAX_ATTEMPTS,
        "read_only_checks": True,
    })
    for iteration in range(1, MAX_ATTEMPTS + 1):
        retry = []
        for case in pending:
            name, payload = case["name"], case["payload"]
            logger.phase("act", {
                "iteration": iteration, "check": name, "path": case["path"], "payload": payload,
            })
            body = None
            retryable = False
            try:
                body = backend.post(case["path"], payload, HTTP_TIMEOUT)
                issues = backend.check(args.mode, name, body, payload)
            except error.HTTPError as exc:
                issues = [f"Backend returned HTTP {exc.code}."]
                retryable = exc.code >= 500 or exc.code == 429
            except (error.URLError, TimeoutError, OSError) as exc:
                issues = [f"Backend request failed: {exc}"]
                retryable = True
            except (ValueError, UnicodeDecodeError) as exc:
                issues = [f"Invalid backend response: {exc}"]
            results[name] = {
                "passed": not issues, "attempts": iteration, "issues": issues, "response": body,
            }
            logger.phase("observe", {"iteration": iteration, "check": name, **results[name]})
            if issues and retryable and iteration < MAX_ATTEMPTS:
                retry.append(case)
        failed = [name for name, result in results.items() if not result["passed"]]
        logger.phase("adapt", {
            "iteration": iteration,
            "decision": "retry_unavailable_checks" if retry else ("fail" if failed else "pass"),
            "retry_checks": [case["name"] for case in retry],
            "failed_checks": failed,
            "guidance": (
                "Check service URLs, feature flags, seeded data and the RAG source sync; "
                "fix failing contracts before rerunning."
                if failed else "All requested response checks passed."
            ),
        })
        if not retry:
            break
        pending = retry
        time.sleep(1)
    return {
        "run_id": run_id,
        "feature": args.feature,
        "mode": args.mode,
        "base_url": args.base_url,
        "setup": setup_info,
        "passed": all(result["passed"] for result in results.values()),
        "checks": results,
        "transcript": logger.transcript_path,
        "scope": "Live backend response validation; answer factual accuracy still needs review.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--mode", choices=("mcp", "rag"), required=True)
    parser.add_argument("--feature", choices=("almanac", "vgarden"), default="almanac")
    parser.add_argument(
        "--base-url", default=None,
        help="almanac: the feature's own base URL (default http://localhost:3000/almanac). "
        "vgarden: vgarden's own base URL (default http://localhost:3000/vgarden).",
    )
    parser.add_argument(
        "--auth-base-url", default="http://localhost:3000/auth",
        help="vgarden only: auth's base URL, used to register/log in and open the garden.",
    )
    parser.add_argument("--log-dir", type=Path, help="directory for private validation transcripts")
    parser.add_argument("--output", type=Path, help="also save the JSON result to this file")
    args = parser.parse_args()
    if args.base_url is None:
        args.base_url = (
            "http://localhost:3000/almanac" if args.feature == "almanac" else "http://localhost:3000/vgarden"
        )
    for url in (args.base_url, args.auth_base_url):
        if urlparse(url).scheme not in ("http", "https"):
            parser.error("--base-url/--auth-base-url must be an http or https URL")
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    result = run(args)
    output = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output + "\n", encoding="utf-8")
    print(output)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

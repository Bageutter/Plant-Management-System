"""End-to-end check of a deployed site, done the way a person uses it.

The smoke test (azure-smoke.sh) proves pages answer. This goes further and
exercises the features across services through the public URL, timing each step:

  auth + vgarden  register, add a garden (auth -> vgarden), see it on the account
                  page (auth -> vgarden), open it (SSO handoff), add an area and a
                  Tomato planting, see them on the garden page
  almanac         the catalogue is seeded; a logged-in visitor is recognised
                  (almanac -> auth); the AI chat says it is switched off (baseline)
  health          create a plant title, list it, delete it (CRUD without a model)
  baseline        vgarden reports MCP, RAG and Multi-Agent disabled

It creates a throwaway account and garden (kept, like the agentic-loop checks).

    python3 scripts/deploy/azure-e2e.py https://plantms-prod-proxy.<env>.azurecontainerapps.io
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from urllib import error, request

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "ai-loop"))
from validate import VgardenSession  # noqa: E402 -- reuse the real browser-style session

SLOW_SECONDS = 5.0
results: list[tuple[str, bool, float, str]] = []


def check(ok: bool, message: str) -> None:
    """Like assert, but not stripped by python -O."""
    if not ok:
        raise AssertionError(message)


def step(name: str, fn):
    started = time.monotonic()
    try:
        detail = fn() or ""
        ok = True
    except Exception as exc:  # report every failure, keep going
        detail, ok = f"{type(exc).__name__}: {exc}", False
    seconds = time.monotonic() - started
    results.append((name, ok, seconds, str(detail)))
    flag = "PASS" if ok else "FAIL"
    slow = "  (slow)" if ok and seconds > SLOW_SECONDS else ""
    print(f"  {flag}  {seconds:5.1f}s  {name}{slow}" + (f"\n          {detail}" if detail else ""), flush=True)


def main() -> int:
    if len(sys.argv) != 2 or not sys.argv[1].startswith("https://"):
        sys.exit("Usage: python3 scripts/deploy/azure-e2e.py https://<public proxy host>")
    base = sys.argv[1].rstrip("/")
    session = VgardenSession(f"{base}/auth", f"{base}/vgarden", timeout=60)
    opener = session.opener

    def get(path: str, accept: str = "text/html") -> tuple[int, str]:
        req = request.Request(base + path, headers={"Accept": accept})  # noqa: S310 -- https only, checked above
        try:
            with opener.open(req, timeout=60) as response:
                return response.status, response.read().decode("utf-8", "replace")
        except error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8", "replace")

    def send(method: str, path: str, body: dict | None = None) -> tuple[int, str]:
        data = json.dumps(body).encode() if body is not None else None
        req = request.Request(base + path, data=data, method=method,  # noqa: S310 -- https only
                              headers={"Content-Type": "application/json", "Accept": "application/json"})
        try:
            with opener.open(req, timeout=60) as response:
                return response.status, response.read().decode("utf-8", "replace")
        except error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8", "replace")

    print(f"End-to-end check of {base}")

    # auth + vgarden: the whole garden journey, across both services
    def journey():
        info = session.bootstrap()
        return f"account {info['email']}, garden {info['garden_id']} with an area and a Tomato planting"
    step("register, add a garden, open it (SSO), add an area and a planting", journey)

    def account_lists_garden():
        status, html = get("/auth/account")
        check(status == 200, f"HTTP {status}")
        check(session.garden_name in html, "the new garden is not on the account page")
        check("load your gardens" not in html and "reach the garden service" not in html, "auth could not reach vgarden")
    step("account page lists the garden (auth -> vgarden)", account_lists_garden)

    def garden_page():
        status, html = get(f"/vgarden/gardens/{session.garden_id}/view")
        check(status == 200, f"HTTP {status}")
        check("Tomato" in html and "Validation bed" in html, "planting or area missing from the garden page")
    step("garden page shows the area and the planting", garden_page)

    # almanac
    def catalogue():
        status, body = get("/almanac/api/plants", "application/json")
        check(status == 200, f"HTTP {status}")
        count = json.loads(body)["count"]
        check(count > 0, "the catalogue is empty")
        return f"{count} plants"
    step("almanac catalogue is seeded", catalogue)

    def almanac_knows_user():
        status, html = get("/almanac/")
        check(status == 200, f"HTTP {status}")
        # A logged-in visitor gets the "+ Add a plant" button (only shown with auth_user).
        check("+ Add a plant" in html, "almanac did not recognise the logged-in user")
    step("almanac recognises the logged-in user (almanac -> auth)", almanac_knows_user)

    # health: CRUD without any model call
    created: dict = {}

    def health_create():
        status, body = send("POST", "/health/plant-health-records/plants", {"name": f"E2E basil {session.garden_id}"})
        check(status in (200, 201), f"HTTP {status}: {body[:200]}")
        created.update(json.loads(body))
        return f"plant {created.get('id')}"
    step("health: create a plant title", health_create)

    def health_list():
        status, body = get("/health/plant-health-records/plants", "application/json")
        check(status == 200, f"HTTP {status}")
        check(f"E2E basil {session.garden_id}" in body, "the new title is not listed")
    step("health: list plant titles", health_list)

    def health_delete():
        status, body = send("DELETE", f"/health/plant-health-records/plants/{created['id']}")
        check(status in (200, 204), f"HTTP {status}: {body[:200]}")
    step("health: delete the plant title", health_delete)

    record: dict = {}

    def health_record_create():
        status, body = send("POST", "/health/plant-health-records/assessments",
                            {"plant_ref": f"E2E basil {session.garden_id}", "description": "Wilting at noon."})
        check(status == 201, f"HTTP {status}: {body[:200]}")
        record.update(json.loads(body))
        check(record.get("ai_mode") == "disabled" and record.get("status") == "unknown",
              f"expected a not-assessed record, got {record.get('status')}")
        return f"record {record['id']} saved, not assessed (AI-Mode off)"
    step("health: create a record with AI-Mode off", health_record_create)

    def health_record_read_delete():
        status, _ = get(f"/health/plant-health-records/assessments/{record['id']}", "application/json")
        check(status == 200, f"read: HTTP {status}")
        status, body = send("DELETE", f"/health/plant-health-records/assessments/{record['id']}")
        check(status in (200, 204), f"delete: HTTP {status}: {body[:200]}")
    step("health: read and delete the record", health_record_read_delete)

    # cloud baseline
    def baseline():
        status, body = get("/vgarden/integrations", "application/json")
        flags = {k: v.get("enabled") for k, v in json.loads(body).items()}
        check(status == 200 and not any(flags.values()), f"AI services enabled: {flags}")
        return str(flags)
    step("cloud baseline: MCP, RAG and Multi-Agent are off", baseline)

    failed = [name for name, ok, _, _ in results if not ok]
    slow = [name for name, ok, seconds, _ in results if ok and seconds > SLOW_SECONDS]
    total = sum(seconds for _, _, seconds, _ in results)
    print(f"\n{len(results) - len(failed)}/{len(results)} passed in {total:.1f}s"
          + (f"; slow (> {SLOW_SECONDS:.0f}s): {', '.join(slow)}" if slow else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

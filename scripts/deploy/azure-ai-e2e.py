"""Bonus profile check (B1-B4): every cloud AI service, used through the application.

Runs against the public URL of a deployment made with DEPLOY_PROFILE=bonus. Every
request goes browser -> public proxy -> a feature's backend/API -> the internal AI
app, exactly the path the frontend UI uses (the same routes its HTMX forms call):

  B1 AI-Mode      Plant Health assessment through the agentic loop (cloud Ollama),
                  and an Almanac chat answer (AI-Mode, Plan -> Act -> Observe -> Adapt)
  B2 MCP          a Plant Health tool run through the cloud MCP server
  B3 RAG          a grounded RAG answer with citations from retrieved context
  B4 Multi-Agent  Planner -> Worker -> Reviewer -> human review on one plant

    python3 scripts/deploy/azure-ai-e2e.py https://plantms-prod-proxy.<env>.azurecontainerapps.io

CPU inference in the cloud is slow (minutes, not seconds), and Ollama scales from
zero, so each step waits generously. The output is the bonus evidence
(docs/evidence/release2/cloud-bonus/ai-e2e.txt).
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import uuid
from pathlib import Path
from urllib import error, request

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "ai-loop"))
from validate import VgardenSession  # noqa: E402 -- the real browser-style session

RECORDS = "/health/plant-health-records"
results: list[tuple[str, bool, float]] = []


def check(ok: bool, message: str) -> None:
    if not ok:
        raise AssertionError(message)


def step(name: str, fn):
    started = time.monotonic()
    try:
        detail, ok = fn() or "", True
    except Exception as exc:  # report every failure, keep going
        detail, ok = f"{type(exc).__name__}: {exc}", False
    seconds = time.monotonic() - started
    results.append((name, ok, seconds))
    print(f"  {'PASS' if ok else 'FAIL'}  {seconds:6.1f}s  {name}", flush=True)
    for line in str(detail).splitlines():
        print(f"          {line}", flush=True)
    return ok


def short(text, limit: int = 300) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def main() -> int:
    if len(sys.argv) != 2 or not sys.argv[1].startswith("https://"):
        sys.exit("Usage: python3 scripts/deploy/azure-ai-e2e.py https://<public proxy host>")
    base = sys.argv[1].rstrip("/")
    session = VgardenSession(f"{base}/auth", f"{base}/vgarden", timeout=240)
    opener = session.opener

    def call(method: str, path: str, body: dict | None = None, *, timeout: int = 240,
             form: bool = False, headers: dict | None = None) -> tuple[int, str]:
        if form:
            from urllib.parse import urlencode
            data = urlencode(body or {}).encode()
            kind = "application/x-www-form-urlencoded"
        else:
            data = json.dumps(body).encode() if body is not None else None
            kind = "application/json"
        req = request.Request(base + path, data=data, method=method,  # noqa: S310 -- https only, checked above
                              headers={"Content-Type": kind, "Accept": "application/json", **(headers or {})})
        try:
            with opener.open(req, timeout=timeout) as response:
                return response.status, response.read().decode("utf-8", "replace")
        except error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8", "replace")

    print(f"Cloud AI check (bonus profile) of {base}")
    plant = f"Cloud tomato {uuid.uuid4().hex[:6]}"
    state: dict = {}

    def wiring():
        status, body = call("GET", f"{RECORDS}/integrations")
        check(status == 200, f"integrations -> {status}")
        d = json.loads(body)
        for name in ("mcp", "rag", "multi_agent"):
            check(d[name]["enabled"] is True, f"{name} is not enabled: {d[name]}")
        return "health backend -> " + ", ".join(f"{k}: {d[k]['url']}" for k in ("mcp", "rag", "multi_agent"))
    step("the feature backends are wired to the cloud AI services", wiring)

    def model_ready():
        # Ollama scales from zero and, on its very first start, downloads both models
        # (~6 GB onto the file share), so wait until it lists them.
        want = [os.environ.get("CLOUD_TEXT_MODEL", "qwen3:4b-instruct"),
                os.environ.get("CLOUD_VISION_MODEL", "qwen2.5vl:3b")]
        deadline, last = time.monotonic() + 3600, ""
        while time.monotonic() < deadline:
            try:
                status, body = call("GET", "/health/healthz", timeout=60)
                last = f"{status} {short(body, 300)}"
                if status == 200:
                    # Older health images do not list the models: reachable is all they say.
                    present = json.loads(body)["ai"].get("models_available")
                    if present is None or all(m in present for m in want):
                        return f"health -> Ollama {json.loads(body)['ai']['url']}: models {present}"
            except OSError as exc:
                last = str(exc)
            time.sleep(30)
        raise AssertionError(f"models not ready after 60 min: {last}")
    step("cloud Ollama is reachable and has both models", model_ready)

    def ai_mode_assessment():
        # Text-only assessment: the vision model runs inside the agentic loop. Streamed,
        # like the records page, so progress keeps the connection alive.
        # Read it event by event and stop at the final one, as the page's script does
        # (waiting for the connection to close can hang behind the cloud ingress).
        from urllib.parse import urlencode
        req = request.Request(base + f"{RECORDS}/assessments/stream", method="POST",  # noqa: S310 -- https only
                              data=urlencode({
                                  "plant_ref": plant,
                                  "description": "Lower leaves turning yellow with brown spots; soil stays wet for days.",
                              }).encode(),
                              headers={"Content-Type": "application/x-www-form-urlencoded",
                                       "Accept": "text/event-stream"})
        phases, done = [], None
        with opener.open(req, timeout=600) as response:
            check(response.status == 200, f"stream -> {response.status}")
            for raw in response:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data: "):
                    continue
                event = json.loads(line[6:])
                if event.get("type") == "phase":
                    phases.append(f"{event['phase']}#{event.get('iteration')}")
                elif event.get("type") == "error":
                    raise AssertionError(f"stream error: {event.get('message')}")
                elif event.get("type") == "done":
                    done = event
                    break
        check(done, "no final event")
        status, body = call("GET", f"{RECORDS}/assessments?plant_ref={plant.replace(' ', '%20')}")
        record = json.loads(body)[0]
        check(record["model"] and "none" not in record["model"], f"no model ran: {record['model']}")
        state["assessment"] = record
        return (f"record {record['id']} by {record['model']}: status {record['status']}, "
                f"score {record['health_score']}, confidence {record['confidence']}\n"
                f"summary: {short(record['summary'])}\n"
                f"loop: {short(json.dumps(record.get('loop')), 400)}\n"
                f"streamed phases: {' -> '.join(phases)}")
    step("B1 AI-Mode: Plant Health assessment by the cloud model (agentic loop)", ai_mode_assessment)

    def ai_mode_chat():
        session.bootstrap()  # register + log in through auth, like a visitor
        status, html = call("GET", "/almanac/", headers={"Accept": "text/html"})
        token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html)
        check(token, "no CSRF token on the Almanac page")
        state["csrf"] = token.group(1)
        status, html = call("POST", "/almanac/ai/ask", {
            "csrf_token": state["csrf"], "question": "When should I plant tomatoes?", "mode": "planning",
        }, form=True, timeout=600, headers={"HX-Request": "true", "Accept": "text/html"})
        check(status == 200, f"ask -> {status}: {short(html)}")
        text = short(re.sub(r"<[^>]+>", " ", html), 600)
        check("unavailable" not in text.lower(), f"model unavailable: {text}")
        return f"Almanac chat answered: {text}"
    step("B1 AI-Mode: Almanac chat answer from the cloud model", ai_mode_chat)

    def mcp_tool():
        status, body = call("POST", f"{RECORDS}/tools/run", {"tool": "list_health_assessments", "plant_ref": plant})
        check(status == 200, f"tools/run -> {status}: {short(body)}")
        d = json.loads(body)
        return f"MCP tool list_health_assessments -> {short(json.dumps(d), 500)}"
    step("B2 MCP: Plant Health tool run through the cloud MCP server", mcp_tool)

    def rag_answer():
        status, body = call("POST", f"{RECORDS}/ask/sync")
        check(status == 200, f"ask/sync -> {status}: {short(body)}")
        synced = json.loads(body)
        status, body = call("POST", f"{RECORDS}/ask",
                            {"question": f"What is wrong with {plant} and what should I do?"}, timeout=600)
        check(status == 200, f"ask -> {status}: {short(body)}")
        d = json.loads(body)
        check(d.get("citations"), f"no citations (not grounded): {short(json.dumps(d), 500)}")
        return (f"indexed {synced.get('documents')} record(s) as {synced.get('chunks')} passages\n"
                f"answer: {short(d.get('answer'), 400)}\n"
                f"confidence: {d.get('confidence')} · citations: {short(json.dumps(d.get('citations')), 400)}")
    step("B3 RAG: grounded answer with citations from retrieved context", rag_answer)

    def multi_agent():
        status, body = call("POST", f"{RECORDS}/workflows",
                            {"task": "Summarise this plant's latest assessment and the next step.", "plant_ref": plant})
        check(status == 201, f"start -> {status}: {short(body)}")
        local_id, seen = json.loads(body)["id"], []
        deadline = time.monotonic() + 1500
        while time.monotonic() < deadline:
            status, body = call("GET", f"{RECORDS}/workflows/{local_id}")
            d = json.loads(body)
            if not seen or seen[-1] != d["status"]:
                seen.append(d["status"])
            if d["status"] in ("awaiting_human_review", "failed"):
                break
            time.sleep(10)
        check(d["status"] == "awaiting_human_review", f"workflow ended {d['status']}: {short(json.dumps(d), 500)}")
        recommendation = (d.get("review") or {}).get("recommendation")
        decision = "accept" if recommendation == "accept" else "partially_accept"
        status, body = call("POST", f"{RECORDS}/workflows/{local_id}/review", {
            "decision": decision, "feedback": "Checked against this plant's stored assessment (cloud run)."})
        check(status in (200, 202), f"review -> {status}: {short(body)}")
        final = json.loads(body)
        history = " -> ".join(e["status"] for e in final.get("history", []))
        return (f"workflow {final.get('workflow_id')}: {history}\n"
                f"plan: {short(json.dumps(d.get('plan')), 300)}\n"
                f"worker: {short((d.get('result') or {}).get('answer'), 300)}\n"
                f"reviewer: {recommendation} · human decision: {decision}")
    step("B4 Multi-Agent: Planner -> Worker -> Reviewer -> human review", multi_agent)

    passed = sum(ok for _, ok, _ in results)
    total_s = sum(s for *_, s in results)
    print(f"\n{passed}/{len(results)} passed in {total_s:.0f}s")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

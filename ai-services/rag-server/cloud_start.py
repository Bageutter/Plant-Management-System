"""Cloud entry point of the RAG server (bonus profile only; never used locally).

Locally the index is built by hand (`POST /rag/ingest/<source>`) and kept in a SQLite
file on the developer's disk. A container's disk is new on every start, so here the
server is started under gunicorn and the index is (re)built from the features' public
APIs at start-up and then every RAG_INGEST_INTERVAL seconds, so newly added
records become answerable without anyone calling the ingest endpoint.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import sys
import time
from urllib import error, request

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s cloud_start: %(message)s")
log = logging.getLogger(__name__)

PORT = os.environ.get("RAG_PORT", "5106")
BASE = f"http://127.0.0.1:{PORT}"
SOURCES = [s.strip() for s in os.environ.get("RAG_INGEST_SOURCES", "almanac,health,vgarden").split(",") if s.strip()]
INTERVAL = int(os.environ.get("RAG_INGEST_INTERVAL", "600"))


def _call(method: str, path: str, timeout: float) -> tuple[int, dict]:
    req = request.Request(BASE + path, method=method, headers={"Accept": "application/json"})  # noqa: S310 -- fixed loopback URL
    try:
        with request.urlopen(req, timeout=timeout) as response:  # noqa: S310 -- fixed loopback URL
            return response.status, json.loads(response.read() or b"{}")
    except error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read() or b"{}")
        except ValueError:
            return exc.code, {}


def _wait_until_up(server: subprocess.Popen) -> bool:
    for _ in range(60):
        if server.poll() is not None:
            return False
        try:
            # 503 = serving, Ollama not reachable yet (it scales from zero): still up.
            if _call("GET", "/healthz", 5)[0] in (200, 503):
                return True
        except OSError:
            pass
        time.sleep(2)
    return False


def _ingest_all() -> None:
    for source in SOURCES:
        try:
            status, body = _call("POST", f"/rag/ingest/{source}", 120)
        except OSError as exc:
            log.warning("ingest %s failed: %s", source, exc)
            continue
        log.info("ingest %s -> %s %s", source, status,
                 {k: body.get(k) for k in ("documents", "chunks", "stored", "error") if k in body})


def main() -> int:
    server = subprocess.Popen([  # noqa: S603 -- fixed argv, no shell
        sys.executable, "-m", "gunicorn", "--bind", f"0.0.0.0:{PORT}", "--workers", "1",
        "--threads", "8", "--timeout", "300", "--access-logfile", "-", "app:create_app()",
    ])
    signal.signal(signal.SIGTERM, lambda *_: server.terminate())
    if not _wait_until_up(server):
        log.error("RAG server did not start")
        server.terminate()
        return server.wait() or 1
    while server.poll() is None:
        _ingest_all()
        deadline = time.monotonic() + INTERVAL
        while server.poll() is None and time.monotonic() < deadline:
            time.sleep(5)
    return server.returncode or 0


if __name__ == "__main__":
    raise SystemExit(main())

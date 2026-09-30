"""Shared local RAG server for the Plant Management System.

One Flask process, run on localhost and never containerised (Release 1 rule).
Feature backends send it questions; it retrieves project context from its chunk
store and answers only from that context, with citations and a confidence
category, through local Ollama. Design: docs/ai/mcp-rag-design.md.

Run from the repository root:

    python ai-services/rag-server/app.py        # http://127.0.0.1:5106
"""

from __future__ import annotations

import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask  # noqa: E402
from jinja2 import ChoiceLoader, FileSystemLoader  # noqa: E402

from config import BASE_DIR, Config  # noqa: E402
from store import ChunkStore  # noqa: E402

SHARED_TEMPLATES = os.path.join(BASE_DIR, "..", "..", "shared", "templates")


def create_app(overrides: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)
    if overrides:
        app.config.update(overrides)

    # Reuse the project-wide header macro when the repo checkout is present.
    app.jinja_loader = ChoiceLoader(
        [app.jinja_loader, FileSystemLoader(os.path.abspath(SHARED_TEMPLATES))]
    )

    app.extensions["chunk_store"] = ChunkStore(app.config["RAG_DATABASE_PATH"])

    from routes import bp

    app.register_blueprint(bp)

    @app.context_processor
    def inject_globals():
        return {
            "ai_model": app.config["OLLAMA_MODEL"],
            "embed_model": app.config["RAG_EMBED_MODEL"] or None,
        }

    return app


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    app = create_app()
    logging.getLogger(__name__).info(
        "shared RAG server listening on http://%s:%s (enabled=%s)",
        app.config["RAG_HOST"],
        app.config["RAG_PORT"],
        app.config["RAG_ENABLED"],
    )
    app.run(host=app.config["RAG_HOST"], port=app.config["RAG_PORT"], threaded=True)


if __name__ == "__main__":
    main()

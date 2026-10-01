"""SQLite chunk store for the RAG server.

A *chunk* is one retrievable passage with its provenance: which feature source it
came from, which record, a human title, a link back to the record, and the text.
Optional dense embeddings are stored as JSON so the store has no numeric
dependencies. The schema is created on first use; `sqlite3` is stdlib.
"""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id     TEXT PRIMARY KEY,           -- "<source>:<source_id>:<part>"
    source       TEXT NOT NULL,
    source_id    TEXT NOT NULL,
    part         TEXT NOT NULL,
    title        TEXT NOT NULL,
    url          TEXT,
    text         TEXT NOT NULL,
    recorded_at  TEXT,                       -- when the underlying record was created
    metadata     TEXT NOT NULL DEFAULT '{}',
    embedding    TEXT,                       -- JSON list of floats, or NULL
    indexed_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS chunks_source ON chunks (source, source_id);
CREATE TABLE IF NOT EXISTS ingest_runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    source       TEXT NOT NULL,
    documents    INTEGER NOT NULL,
    chunks       INTEGER NOT NULL,
    finished_at  TEXT NOT NULL
);
"""


@dataclass
class Chunk:
    source: str
    source_id: str
    part: str
    title: str
    text: str
    url: str | None = None
    recorded_at: str | None = None
    metadata: dict = field(default_factory=dict)
    embedding: list[float] | None = None

    @property
    def chunk_id(self) -> str:
        return f"{self.source}:{self.source_id}:{self.part}"

    def to_dict(self) -> dict:
        data = asdict(self)
        data["chunk_id"] = self.chunk_id
        return data


class ChunkStore:
    def __init__(self, path: str):
        self.path = path
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)

    def close(self) -> None:
        self._conn.close()

    # -- writes ------------------------------------------------------------

    def replace_source(self, source: str, chunks: list[Chunk], documents: int) -> int:
        """Replace every chunk of `source` with `chunks` in one transaction.

        Re-ingesting is therefore idempotent and removes chunks whose record was
        deleted in the owning service.
        """

        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._conn:
            self._conn.execute("DELETE FROM chunks WHERE source = ?", (source,))
            self._conn.executemany(
                "INSERT INTO chunks (chunk_id, source, source_id, part, title, url, text, "
                "recorded_at, metadata, embedding, indexed_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        c.chunk_id,
                        c.source,
                        c.source_id,
                        c.part,
                        c.title,
                        c.url,
                        c.text,
                        c.recorded_at,
                        json.dumps(c.metadata, ensure_ascii=False),
                        json.dumps(c.embedding) if c.embedding is not None else None,
                        now,
                    )
                    for c in chunks
                ],
            )
            self._conn.execute(
                "INSERT INTO ingest_runs (source, documents, chunks, finished_at) "
                "VALUES (?, ?, ?, ?)",
                (source, documents, len(chunks), now),
            )
        return len(chunks)

    # -- reads -------------------------------------------------------------

    def chunks(
        self,
        sources: tuple[str, ...] | list[str] | None = None,
        *,
        source_id: str | None = None,
    ) -> list[Chunk]:
        """Retrievable chunks, optionally narrowed to one ``source_id``.

        ``source_id`` scopes retrieval to one record within a source — e.g. one
        garden's chunks within the ``vgarden`` source — so a question can be
        grounded in exactly one owner's record and never another's. See
        ``pipeline.answer`` and ``routes.py``'s ``/rag/query``.
        """

        sql = "SELECT * FROM chunks"
        clauses: list[str] = []
        params: list[str] = []
        if sources:
            clauses.append(f"source IN ({','.join('?' * len(sources))})")
            params.extend(sources)
        if source_id is not None:
            clauses.append("source_id = ?")
            params.append(source_id)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        return [_row_to_chunk(row) for row in self._conn.execute(sql, tuple(params))]

    def get(self, chunk_id: str) -> Chunk | None:
        row = self._conn.execute("SELECT * FROM chunks WHERE chunk_id = ?", (chunk_id,)).fetchone()
        return _row_to_chunk(row) if row else None

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]

    def sources(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT source, COUNT(*) AS chunks, COUNT(DISTINCT source_id) AS documents, "
            "MAX(indexed_at) AS last_indexed_at FROM chunks GROUP BY source"
        ).fetchall()
        return [dict(row) for row in rows]


def _row_to_chunk(row: sqlite3.Row) -> Chunk:
    return Chunk(
        source=row["source"],
        source_id=row["source_id"],
        part=row["part"],
        title=row["title"],
        text=row["text"],
        url=row["url"],
        recorded_at=row["recorded_at"],
        metadata=json.loads(row["metadata"] or "{}"),
        embedding=json.loads(row["embedding"]) if row["embedding"] else None,
    )

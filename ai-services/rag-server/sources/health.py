"""Plant Health assessments as a knowledge source.

Pulls ``GET /plant-health-records/assessments`` from the health service's public
API (never its database) and turns each record into a few focused passages —
summary, gardener's description, issues, recommendations, missing information —
each citing the record by id and linking back to it. Re-ingesting replaces the
whole source, so edits and deletions in the health service are reflected.
"""

from __future__ import annotations

import logging

import requests

from embeddings import EmbeddingUnavailable, build_embedder
from sources import SourceUnavailable
from store import Chunk

logger = logging.getLogger(__name__)

SOURCE = "health"
IMPLEMENTED = True
PAGE_SIZE = 200
MAX_PAGES = 50  # 10 000 records; well beyond a home garden


def fetch_assessments(config) -> list[dict]:
    """Every assessment, newest first, paged through the public list endpoint."""

    base = config["HEALTH_SERVICE_URL"].rstrip("/")
    timeout = config.get("SERVICE_TIMEOUT", 15)
    records: list[dict] = []
    seen: set[int] = set()
    for page in range(MAX_PAGES):
        try:
            response = requests.get(
                f"{base}/plant-health-records/assessments",
                params={"limit": PAGE_SIZE, "offset": page * PAGE_SIZE},
                timeout=timeout,
            )
            response.raise_for_status()
            batch = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise SourceUnavailable(
                f"The Plant Health service at {base} could not be read "
                f"({exc.__class__.__name__}). Is the application stack running?"
            ) from exc
        if not isinstance(batch, list):
            raise SourceUnavailable("The Plant Health service returned an unexpected shape.")
        fresh = [r for r in batch if isinstance(r, dict) and r.get("id") not in seen]
        if not fresh:
            break
        records.extend(fresh)
        seen.update(r["id"] for r in fresh)
        if len(batch) < PAGE_SIZE:
            break
    return records


def chunks_for(record: dict, public_url: str) -> list[Chunk]:
    """Split one assessment into citable passages."""

    record_id = str(record["id"])
    name = record.get("plant_ref") or record.get("plant_identification") or "an unnamed plant"
    title = f"Assessment #{record_id} — {name}"
    url = f"{public_url.rstrip('/')}/plant-health-records/{record_id}"
    recorded_at = record.get("created_at")
    metadata = {
        "plant_ref": record.get("plant_ref"),
        "plant_identification": record.get("plant_identification"),
        "status": record.get("status"),
        "health_score": record.get("health_score"),
        "confidence": record.get("confidence"),
        "created_at": recorded_at,
    }

    def chunk(part: str, text: str) -> Chunk:
        return Chunk(
            source=SOURCE,
            source_id=record_id,
            part=part,
            title=title,
            text=text,
            url=url,
            recorded_at=recorded_at,
            metadata=metadata,
        )

    chunks: list[Chunk] = []

    status = (record.get("status") or "unknown").replace("_", " ")
    score = record.get("health_score")
    score_text = (
        f"health score {score}/100" + (f", {record['score_band']}" if record.get("score_band") else "")
        if score is not None
        else "no health score"
    )
    identification = record.get("plant_identification")
    summary = (
        f"Plant health assessment of {name}"
        + (f", identified as {identification}" if identification and identification != name else "")
        + f". Recorded {recorded_at or 'at an unknown time'}. Status: {status} ({score_text})."
    )
    if record.get("confidence"):
        summary += f" Model confidence: {record['confidence']}"
        if record.get("confidence_reason"):
            summary += f" — {record['confidence_reason']}"
        summary += "."
    if record.get("summary"):
        summary += f" Summary: {record['summary']}"
    chunks.append(chunk("summary", summary))

    if record.get("description"):
        chunks.append(chunk("description", f"Gardener's description of {name}: {record['description']}"))

    issues = [
        f"{i.get('name')} ({i.get('severity', 'medium')} severity)"
        + (f" — evidence: {i['evidence']}" if i.get("evidence") else "")
        for i in record.get("issues") or []
        if isinstance(i, dict) and i.get("name")
    ]
    if issues:
        chunks.append(chunk("issues", f"Observed issues for {name}: " + "; ".join(issues) + "."))

    recommendations = [
        f"{r.get('action')} ({r.get('priority', 'medium')} priority)"
        + (f": {r['details']}" if r.get("details") else "")
        for r in record.get("recommendations") or []
        if isinstance(r, dict) and r.get("action")
    ]
    if recommendations:
        chunks.append(
            chunk(
                "recommendations",
                f"Recommended actions for {name}: " + "; ".join(recommendations) + ".",
            )
        )

    missing = [str(m).strip() for m in record.get("missing_information") or [] if str(m).strip()]
    if missing:
        chunks.append(
            chunk("missing", f"Information that would help assess {name}: " + "; ".join(missing) + ".")
        )

    return chunks


def ingest(config, store, embedder=None) -> dict:
    records = fetch_assessments(config)
    public_url = config.get("HEALTH_PUBLIC_URL") or config["HEALTH_SERVICE_URL"]
    chunks = [c for record in records for c in chunks_for(record, public_url)]

    embedded = False
    embedder = embedder if embedder is not None else build_embedder(config)
    if embedder is not None and chunks:
        try:
            vectors = embedder.embed([f"{c.title}\n{c.text}" for c in chunks])
            for chunk, vector in zip(chunks, vectors):
                chunk.embedding = vector
            embedded = True
        except EmbeddingUnavailable as exc:
            logger.warning("indexing health without embeddings: %s", exc)

    stored = store.replace_source(SOURCE, chunks, documents=len(records))
    return {
        "source": SOURCE,
        "documents": len(records),
        "chunks": stored,
        "embedded": embedded,
        "public_url": public_url.rstrip("/"),
    }

"""Virtual Garden state as a knowledge source.

Pulls the bulk, service-token-authenticated ``GET /gardens/export`` endpoint from
vgarden's own API (never its database — see ``vgarden/routes.py::export_gardens``)
and turns each garden into a few focused passages: summary, areas, containers,
plantings. Each chunk's ``source_id`` is the garden id, which is what lets a
query be scoped to one garden (``ChunkStore.chunks``'s ``source_id`` filter, used
by ``RagClient.ask`` in ``vgarden/integrations.py``) — garden state is private
per-owner, unlike the public Almanac catalogue or Plant Health assessments, so
retrieval must never cross from one owner's garden into another's. Re-ingesting
replaces the whole source, so edits/deletions in vgarden are reflected.
"""

from __future__ import annotations

import logging

import requests

from embeddings import EmbeddingUnavailable, build_embedder
from sources import SourceUnavailable
from store import Chunk

logger = logging.getLogger(__name__)

SOURCE = "vgarden"
IMPLEMENTED = True


def fetch_gardens(config) -> list[dict]:
    """Every garden's full snapshot, via vgarden's authenticated bulk export."""

    base = config["VGARDEN_SERVICE_URL"].rstrip("/")
    token = config.get("VGARDEN_SERVICE_TOKEN", "")
    try:
        response = requests.get(
            f"{base}/gardens/export",
            headers={"Authorization": f"Bearer {token}"},
            timeout=config.get("SERVICE_TIMEOUT", 15),
        )
        response.raise_for_status()
        gardens = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise SourceUnavailable(
            f"The Virtual Garden service at {base} could not be read "
            f"({exc.__class__.__name__}). Is the application stack running?"
        ) from exc
    if not isinstance(gardens, list):
        raise SourceUnavailable("The Virtual Garden service returned an unexpected shape.")
    return gardens


def chunks_for(garden: dict, public_url: str) -> list[Chunk]:
    """Split one garden snapshot into citable passages, scoped by its garden id."""

    garden_id = str(garden["garden_id"])
    name = garden.get("name") or f"Garden #{garden_id}"
    title = f"Garden — {name}"
    url = f"{public_url.rstrip('/')}/gardens/{garden_id}/view"
    metadata = {
        "location_label": garden.get("location_label"),
        "climate_zone": garden.get("climate_zone"),
    }

    def chunk(part: str, text: str) -> Chunk:
        return Chunk(
            source=SOURCE,
            source_id=garden_id,
            part=part,
            title=title,
            text=text,
            url=url,
            metadata=metadata,
        )

    chunks: list[Chunk] = []
    areas = garden.get("areas") or []
    containers = garden.get("containers") or []
    plantings = garden.get("plantings") or []

    summary = f"Garden '{name}'."
    if garden.get("location_label"):
        summary += f" Location: {garden['location_label']}."
    if garden.get("climate_zone"):
        summary += f" Climate zone: {garden['climate_zone']}."
    summary += (
        f" {len(areas)} area(s), {len(containers)} container(s), "
        f"{len(plantings)} planting(s) recorded."
    )
    if garden.get("evidence_note"):
        summary += f" {garden['evidence_note']}"
    chunks.append(chunk("summary", summary))

    if areas:
        lines = [
            f"{a.get('name')} ({a.get('area_type', 'bed')}, {a.get('width')}×{a.get('length')} m)"
            + (f" — {a['notes']}" if a.get("notes") else "")
            for a in areas
        ]
        chunks.append(chunk("areas", f"Garden areas in {name}: " + "; ".join(lines) + "."))

    if containers:
        lines = [f"{c.get('name')} ({c.get('container_type', 'pot')})" for c in containers]
        chunks.append(chunk("containers", f"Containers in {name}: " + "; ".join(lines) + "."))

    if plantings:
        lines = [
            f"{p.get('crop_name')}"
            + (f" ×{p['quantity']}" if p.get("quantity") else "")
            + f" — {p.get('lifecycle_state') or 'planned'}"
            + (f", {p['growth_stage']}" if p.get("growth_stage") else "")
            + (f" at {p['location']}" if p.get("location") else "")
            + (f", planted {p['planted_date']}" if p.get("planted_date") else "")
            + (
                f", expected harvest {p['expected_harvest_date']}"
                if p.get("expected_harvest_date")
                else ""
            )
            for p in plantings
        ]
        chunks.append(chunk("plantings", f"Plantings in {name}: " + "; ".join(lines) + "."))

    return chunks


def ingest(config, store, embedder=None) -> dict:
    gardens = fetch_gardens(config)
    public_url = config.get("VGARDEN_PUBLIC_URL") or config["VGARDEN_SERVICE_URL"]
    chunks = [c for garden in gardens for c in chunks_for(garden, public_url)]

    embedded = False
    embedder = embedder if embedder is not None else build_embedder(config)
    if embedder is not None and chunks:
        try:
            vectors = embedder.embed([f"{c.title}\n{c.text}" for c in chunks])
            if len(vectors) != len(chunks):
                raise EmbeddingUnavailable("Not all vgarden chunks received embeddings")
            for chunk, vector in zip(chunks, vectors):
                chunk.embedding = vector
            embedded = True
        except EmbeddingUnavailable as exc:
            logger.warning("indexing vgarden without embeddings: %s", exc)

    stored = store.replace_source(SOURCE, chunks, documents=len(gardens))
    return {
        "source": SOURCE,
        "documents": len(gardens),
        "chunks": stored,
        "embedded": embedded,
        "public_url": public_url.rstrip("/"),
    }

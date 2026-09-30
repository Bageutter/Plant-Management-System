"""Index public Almanac plants and pest/disease guides through its read-only API."""

from __future__ import annotations

import logging
from urllib.parse import quote

import requests

from embeddings import EmbeddingUnavailable, build_embedder
from sources import SourceUnavailable
from store import Chunk

logger = logging.getLogger(__name__)

SOURCE = "almanac"
IMPLEMENTED = True
PAGE_SIZE = 50  # the catalogue API's maximum
MAX_PAGES = 100  # fail beyond 5,000 records, rather than index a partial catalogue
PLURALS = {"plant": "plants", "pest": "pests", "disease": "diseases"}


def _get(config, path, params=None):
    base = config["ALMANAC_SERVICE_URL"].rstrip("/")
    try:
        response = requests.get(
            f"{base}/api/catalogue{path}",
            params=params,
            timeout=config.get("SERVICE_TIMEOUT", 15),
        )
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise SourceUnavailable(
            f"The Plant Almanac service at {base} could not be read "
            f"({exc.__class__.__name__}). Is the application stack running?"
        ) from exc
    if not isinstance(data, dict):
        raise SourceUnavailable("The Plant Almanac service returned an unexpected shape.")
    return data


def fetch_catalogue(config) -> list[dict]:
    """Read the complete catalogue before replacing any previously indexed data."""
    references = []
    seen = set()
    offset = 0
    total = None
    for _ in range(MAX_PAGES):
        page = _get(config, "", {"limit": PAGE_SIZE, "offset": offset})
        batch = page.get("items")
        page_total = page.get("total")
        if (
            not isinstance(batch, list)
            or type(page_total) is not int
            or page_total < 0
            or page.get("offset") != offset
            or "next_offset" not in page
        ):
            raise SourceUnavailable("The Plant Almanac catalogue returned invalid pagination.")
        if total is None:
            total = page_total
        if total != page_total or len(batch) != min(PAGE_SIZE, total - offset):
            raise SourceUnavailable(
                "The Plant Almanac catalogue changed or returned an incomplete page; retry indexing."
            )
        for item in batch:
            if (
                not isinstance(item, dict)
                or item.get("kind") not in PLURALS
                or not isinstance(item.get("key"), str)
                or not item["key"]
            ):
                raise SourceUnavailable(
                    "The Plant Almanac catalogue returned an invalid reference."
                )
            identity = (item["kind"], item["key"])
            if identity in seen:
                raise SourceUnavailable(
                    "The Plant Almanac catalogue repeated a record; retry indexing."
                )
            seen.add(identity)
            references.append(item)
        offset += len(batch)
        if offset == total:
            if page["next_offset"] is not None:
                raise SourceUnavailable("The Plant Almanac catalogue returned invalid pagination.")
            break
        if page["next_offset"] != offset:
            raise SourceUnavailable("The Plant Almanac catalogue skipped or repeated a page.")
    else:
        raise SourceUnavailable(
            "The Plant Almanac catalogue exceeds the indexing page limit; the previous index was kept."
        )

    records = []
    for item in references:
        detail = _get(config, f"/{item['kind']}/{quote(item['key'], safe='')}")
        if (
            detail.get("kind") != item["kind"]
            or detail.get("key") != item["key"]
            or not isinstance(detail.get("name"), str)
            or not detail["name"].strip()
            or (item["kind"] == "plant" and not isinstance(detail.get("record"), dict))
            or (item["kind"] != "plant" and not isinstance(detail.get("guide"), (dict, type(None))))
            or (item["kind"] != "plant" and "guide" not in detail)
        ):
            raise SourceUnavailable(
                "The Plant Almanac catalogue returned an invalid detail record."
            )
        records.append(detail)
    return records


def chunk_for(detail: dict, public_url: str) -> Chunk:
    """Keep each catalogue entry and its limitations together in one citation."""
    kind, key, name = detail["kind"], detail["key"], detail["name"]
    lines = [f"Plant Almanac {kind}: {name}."]
    metadata = {"kind": kind, "key": key}

    if kind == "plant":
        record = detail["record"]
        fields = {
            "scientific_name": "Scientific name",
            "family": "Family",
            "summary": "Summary",
            "water_needs": "Water needs",
            "sun_needs": "Sun needs",
            "care_notes": "Care",
            "sowing_notes": "Sowing notes",
            "planting_months": "Recorded planting months",
            "soil_ph_min": "Minimum soil pH",
            "soil_ph_max": "Maximum soil pH",
            "in_row_spacing_cm": "In-row spacing (cm)",
            "row_spacing_cm": "Row spacing (cm)",
            "succession_interval_days": "Succession interval (days)",
            "harvest_window_weeks": "Harvest window (weeks)",
            "yield_qty": "Yield per plant",
            "yield_unit": "Yield unit",
            "yield_wording": "Yield notes",
            "feeder_type": "Feeder type",
            "forest_layer": "Forest layer",
            "part_used": "Part used",
            "uses": "Uses",
            "uses_notes": "Uses notes",
            "function_tags": "Garden functions",
            "management_notes": "Management notes",
            "pests": "Associated pests",
            "diseases": "Associated diseases",
            "source_url": "Recorded reference source",
        }
        for field, label in fields.items():
            value = record.get(field)
            if value is not None and value != "" and value != []:
                if isinstance(value, list):
                    value = ", ".join(str(item) for item in value)
                lines.append(f"{label}: {value}.")
        rotation = record.get("rotation_group")
        if rotation:
            lines.append(
                f"Rotation group: {rotation.get('name')}; feeder weight: "
                f"{rotation.get('feeder_weight')}; rotation exempt: {rotation.get('is_rotation_exempt')}."
            )
        for companion in record.get("guild_links") or []:
            lines.append(
                f"Recorded companion: {companion.get('name')}; function: "
                f"{companion.get('function')}; notes: {companion.get('notes') or 'not recorded'}."
            )
        lines.append(
            "Missing fields are not recorded. Plant-pest and plant-disease links are catalogue associations, not confirmed diagnoses."
        )
    else:
        if detail.get("description"):
            lines.append(detail["description"])
        guide = detail.get("guide")
        metadata["guide_available"] = guide is not None
        if guide is None:
            lines.append(
                "No management guide is available for this entry. Do not invent treatment instructions."
            )
        else:
            for field in ("intro", "status", "spray_note"):
                if guide.get(field):
                    lines.append(f"{field.replace('_', ' ').capitalize()}: {guide[field]}")
            for sign in guide.get("signs") or []:
                lines.append(f"Recorded sign: {sign}")
            for step in guide.get("control_steps") or []:
                lines.append(f"Management step — {step.get('title', '')}: {step.get('body', '')}")
            for companion in guide.get("companions") or []:
                lines.append(f"Support — {companion.get('name', '')}: {companion.get('body', '')}")
            for source in guide.get("sources") or []:
                lines.append(f"Guide source: {source.get('label', '')} {source.get('url', '')}")
        # Related plants are paged separately by the API; do not index an incomplete list.
        lines.append("This is reference guidance, not a diagnosis of the gardener's plant.")
    if detail.get("evidence_note"):
        lines.append(detail["evidence_note"])

    return Chunk(
        source=SOURCE,
        source_id=f"{kind}:{key}",
        part="record",
        title=f"{name} — {kind} reference",
        text="\n".join(lines),
        url=f"{public_url.rstrip('/')}/{PLURALS[kind]}/{quote(key, safe='')}",
        metadata=metadata,
    )


def ingest(config, store, embedder=None) -> dict:
    records = fetch_catalogue(config)
    public_url = config.get("ALMANAC_PUBLIC_URL") or config["ALMANAC_SERVICE_URL"]
    chunks = [chunk_for(record, public_url) for record in records]
    embedded = False
    embedder = embedder if embedder is not None else build_embedder(config)
    if embedder is not None and chunks:
        try:
            vectors = embedder.embed([f"{chunk.title}\n{chunk.text}" for chunk in chunks])
            if len(vectors) != len(chunks):
                raise EmbeddingUnavailable("Not all Almanac chunks received embeddings")
            for chunk, vector in zip(chunks, vectors):
                chunk.embedding = vector
            embedded = True
        except EmbeddingUnavailable as exc:
            logger.warning("indexing almanac without embeddings: %s", exc)

    stored = store.replace_source(SOURCE, chunks, documents=len(records))
    return {
        "source": SOURCE,
        "documents": len(records),
        "chunks": stored,
        "embedded": embedded,
        "public_url": public_url.rstrip("/"),
    }

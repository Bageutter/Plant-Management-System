"""Plant Almanac reference records as a knowledge source — stub.

The Almanac's public catalogue API (PR #36) is the natural feed: one chunk per
plant record plus one per pest/disease guide. Tracked by the Almanac RAG issue
linked from ai-services/rag-server/README.md.
"""

from __future__ import annotations

from sources import SourceNotImplemented

SOURCE = "almanac"
TRACKING = "GitHub issue #43 (Bageutter/Plant-Management-System)"


def ingest(config, store) -> dict:
    raise SourceNotImplemented(SOURCE, TRACKING)

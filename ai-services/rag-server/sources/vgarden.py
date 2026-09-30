"""Virtual Garden state as a knowledge source — stub.

Garden pages are owner-scoped, so indexing them needs an inter-service read
endpoint on the vgarden side first. Tracked by the Virtual Garden RAG issue linked
from ai-services/rag-server/README.md.
"""

from __future__ import annotations

from sources import SourceNotImplemented

SOURCE = "vgarden"
TRACKING = "GitHub issue #44 (Bageutter/Plant-Management-System)"


def ingest(config, store) -> dict:
    raise SourceNotImplemented(SOURCE, TRACKING)

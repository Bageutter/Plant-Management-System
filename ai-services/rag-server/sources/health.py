"""Plant Health assessments as a knowledge source.

Stub in this branch. The implementation (branch claude/health-mcp-rag-integration)
pulls ``GET /plant-health-records/assessments`` from the health service's public
API and turns each record into summary / issues / recommendations chunks that
cite the record by id and URL.
"""

from __future__ import annotations

from sources import SourceNotImplemented

SOURCE = "health"
TRACKING = "docs/ai/mcp-rag-design.md section 3 (branch claude/health-mcp-rag-integration)"


def ingest(config, store) -> dict:
    raise SourceNotImplemented(SOURCE, TRACKING)

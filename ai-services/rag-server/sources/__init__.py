"""Knowledge sources the RAG server can index, one module per feature service.

Each module exposes ``ingest(config, store) -> dict`` and raises
``SourceNotImplemented`` while it is still a stub, which the API surfaces as 501.
"""

from __future__ import annotations


class SourceNotImplemented(NotImplementedError):
    """A registered source whose ingestion has not been built yet."""

    def __init__(self, source: str, tracking: str):
        super().__init__(
            f"Ingestion for the '{source}' source is not implemented in the shared RAG "
            f"server yet; tracked in {tracking}."
        )
        self.source = source
        self.tracking = tracking


class SourceUnavailable(RuntimeError):
    """The owning feature service could not be reached or answered unexpectedly."""

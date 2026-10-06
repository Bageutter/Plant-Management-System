"""Persistent vector index. Original application databases remain authoritative.

Refresh builds a new collection before atomically activating its manifest entry.
Failed refreshes leave the previous collection active. Old collections are retained
for recovery; do not run multiple writer processes against the same directory.
"""
import json
import math
import os
import threading
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import chromadb
from chromadb.config import Settings
from store import Chunk


class ChromaStore:
    def __init__(self, path, model):
        if not model:
            raise ValueError("Chroma requires RAG_EMBED_MODEL.")
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=str(self.path), settings=Settings(anonymized_telemetry=False))
        self.model = model
        self.lock = threading.Lock()
        self.manifest_path = self.path / 'active.json'
        self.active = json.loads(self.manifest_path.read_text()) if self.manifest_path.exists() else {}
        if any(row['model'] != model for row in self.active.values()):
            raise ValueError('Embedding model changed: use a new RAG_CHROMA_PATH and reindex.')

    def replace_source(self, source, chunks, documents):
        with self.lock:
            dimensions = {len(c.embedding or []) for c in chunks}
            if chunks and (0 in dimensions or len(dimensions) != 1 or any(
                not all(math.isfinite(v) for v in c.embedding) or not any(c.embedding) for c in chunks
            )):
                raise ValueError('Refresh requires valid embeddings for every passage; previous index retained.')
            if any(c.source != source for c in chunks) or len({c.chunk_id for c in chunks}) != len(chunks):
                raise ValueError('Invalid source or duplicate passage IDs.')
            name = f'pms-{source}-{uuid.uuid4().hex}'
            collection = self.client.create_collection(name, embedding_function=None, metadata={'hnsw:space': 'cosine'})
            for offset in range(0, len(chunks), 100):
                batch = chunks[offset:offset + 100]
                collection.add(ids=[c.chunk_id for c in batch], embeddings=[c.embedding for c in batch],
                    documents=[c.text for c in batch], metadatas=[{'source_id': str(c.source_id),
                    'payload': json.dumps(asdict(c))} for c in batch])
            manifest = dict(self.active)
            manifest[source] = {'collection': name, 'model': self.model, 'documents': documents,
                'chunks': len(chunks), 'last_indexed_at': datetime.now(timezone.utc).isoformat()}
            temporary = self.manifest_path.with_suffix('.tmp')
            temporary.write_text(json.dumps(manifest, indent=2))
            os.replace(temporary, self.manifest_path)
            self.active = manifest
            return len(chunks)

    def _collections(self, sources):
        for source, row in list(self.active.items()):
            if sources is None or source in sources:
                yield self.client.get_collection(row['collection'], embedding_function=None)

    def chunks(self, sources=None, *, source_id=None):
        with self.lock:
            result = []
            for collection in self._collections(sources):
                data = collection.get(where={'source_id': str(source_id)} if source_id is not None else None)
                result.extend(Chunk(**json.loads(m['payload'])) for m in data['metadatas'])
            return result

    def vector_chunks(self, embedding, sources, *, source_id=None, top_k=5):
        with self.lock:
            hits = []
            for collection in self._collections(sources):
                if not collection.count():
                    continue
                data = collection.query(query_embeddings=[embedding], n_results=min(top_k, collection.count()),
                    where={'source_id': str(source_id)} if source_id is not None else None,
                    include=['metadatas', 'distances'])
                hits.extend((distance, Chunk(**json.loads(meta['payload']))) for distance, meta in
                    zip(data['distances'][0], data['metadatas'][0]))
            return [chunk for _, chunk in sorted(hits, key=lambda item: item[0])[:top_k]]

    def get(self, chunk_id):
        return next((c for c in self.chunks() if c.chunk_id == chunk_id), None)

    def sources(self):
        return [dict(source=source, **row) for source, row in self.active.items()]

    def count(self):
        return sum(row['chunks'] for row in self.active.values())

    def close(self):
        pass

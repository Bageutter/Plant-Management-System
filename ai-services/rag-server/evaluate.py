"""Reproducible retrieval benchmark; draft labels are not answer-truth judgments."""
import argparse
import hashlib
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


def metrics(ids, relevant, k=5):
    found = len(set(ids) & set(relevant))
    return {'precision_at_5': found / k if relevant else None,
            'recall_at_5': found / len(set(relevant)) if relevant else None,
            'reciprocal_rank': next((1 / i for i, cid in enumerate(ids, 1) if cid in relevant), 0) if relevant else None}


def mean(values):
    return sum(values) / len(values) if values else None


def main():
    from chroma_store import ChromaStore
    from config import Config
    from embeddings import build_embedder
    from retrieval import retrieve

    parser = argparse.ArgumentParser()
    parser.add_argument('--queries', default=str(Path(__file__).parent / 'evaluation/queries.json'))
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    config = {key: getattr(Config, key) for key in dir(Config) if key.isupper()}
    store = ChromaStore(config['RAG_CHROMA_PATH'], config['RAG_EMBED_MODEL'])
    all_chunks = store.chunks()
    labels = json.loads(Path(args.queries).read_text())
    embedder = build_embedder(config)
    rows = []
    for query in labels:
        sources = query.get('sources', ['almanac'])
        scope = query.get('source_id')
        chunks = store.chunks(sources, source_id=scope)
        relevant = set(query['relevant_ids'])
        if not relevant <= {c.chunk_id for c in chunks}:
            raise ValueError(f"Missing or out-of-scope labels: {query['id']}")
        question = query['question']
        start = time.perf_counter()
        vector = embedder.embed([question])[0]
        vector_hits = store.vector_chunks(vector, sources, source_id=scope, top_k=5)
        vector_ms = (time.perf_counter() - start) * 1000
        start = time.perf_counter()
        lexical = retrieve(question, chunks, top_k=5, min_coverage=0, min_similarity=0)
        lexical_ms = (time.perf_counter() - start) * 1000
        for mode, hits, elapsed in [('lexical', [c.chunk for c in lexical.candidates], lexical_ms), ('chroma', vector_hits, vector_ms)]:
            # Match the production gate/reranker; this does not exercise generation or shortcuts.
            gated = retrieve(question, vector_hits if mode == 'chroma' else chunks, top_k=5,
                             min_coverage=config['RAG_MIN_COVERAGE'], min_similarity=config['RAG_MIN_SIMILARITY'],
                             query_embedding=vector if mode == 'chroma' else None)
            ids = [c.chunk_id for c in hits]
            gated_ids = [c.chunk.chunk_id for c in gated.candidates]
            rows.append(dict(id=query['id'], question=question, category=query['category'], sources=sources,
                source_id=scope, mode=mode, relevant_ids=sorted(relevant), retrieved=ids,
                gated_retrieved=gated_ids, **metrics(ids, relevant), gated_metrics=metrics(gated_ids,relevant),
                negative_rejected=(not gated_ids) if not relevant else None,
                scope_ok=all(c.source in sources and (scope is None or str(c.source_id)==str(scope)) for c in hits),
                latency_ms=round(elapsed,2)))
    summaries=[]
    for mode in ('lexical','chroma'):
        for source in ('all','almanac','health','vgarden'):
            selected=[r for r in rows if r['mode']==mode and (source=='all' or source in r['sources'])]
            positive=[r for r in selected if r['relevant_ids']]
            negative=[r for r in selected if not r['relevant_ids']]
            summaries.append(dict(mode=mode,source=source,positive_queries=len(positive),negative_queries=len(negative),
                **{key:mean([r[key] for r in positive]) for key in ('precision_at_5','recall_at_5','reciprocal_rank')},
                gated_recall_at_5=mean([r['gated_metrics']['recall_at_5'] for r in positive]),
                negative_rejections=sum(r['negative_rejected'] for r in negative),scope_violations=sum(not r['scope_ok'] for r in selected)))
    result={'timestamp_utc':datetime.now(timezone.utc).isoformat(),
        'note':'Exploratory, assistant-authored labels based on indexed records; human review pending. Retrieval only, not answer factuality, UI, authentication or full release validation.',
        'commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
        'working_tree_dirty':bool(subprocess.check_output(['git','status','--porcelain'],text=True).strip()),
        'evaluator_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'embedding_model':config['RAG_EMBED_MODEL'], 'embedding_dimensions':len(vector),
        'index_sources':store.sources(),
        'dataset_sha256':hashlib.sha256(json.dumps([(c.chunk_id,c.text,c.source_id,c.embedding) for c in sorted(all_chunks,key=lambda c:c.chunk_id)]).encode()).hexdigest(),
        'labels_sha256':hashlib.sha256(Path(args.queries).read_bytes()).hexdigest(),
        'thresholds':{k:config[k] for k in ('RAG_MIN_COVERAGE','RAG_MIN_SIMILARITY')},
        'summary':summaries,'results':rows}
    Path(args.output).parent.mkdir(parents=True,exist_ok=True)
    Path(args.output).write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(summaries,indent=2))

if __name__ == '__main__':
    main()

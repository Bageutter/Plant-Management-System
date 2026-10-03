"""Retrieval: lexical BM25 (always available) plus optional dense similarity.

Pure Python by design — the corpus is a few hundred passages of project records,
so an in-memory index built per query is faster than any dependency would be.
Every candidate carries a *relevance* score in [0, 1] and the raw signals it was
built from, so the API can show why a passage was retrieved and the confidence
category can be derived from measurable evidence rather than from the model.
"""

from __future__ import annotations

import math
from difflib import get_close_matches
import re
from collections import Counter
from dataclasses import dataclass

from store import Chunk

_TOKEN_RE = re.compile(r"[a-z0-9]+")
STOPWORDS = frozenset(
    """
    a about above after again all also am an and any are as at be because been before
    being below between both but by can could did do does doing down during each few for
    from further had has have having he her here hers him his how i if in into is it its
    itself just me more most my no nor not of off on once only or other our ours out over
    own same she should so some such than that the their theirs them then there these they
    this those through to too under until up very was we were what when where which while
    who whom why will with would you your yours compare versus vs
    """.split()
)


def tokenize(text: str) -> list[str]:
    """Lower-case word tokens minus stopwords, with a light suffix fold.

    The fold (``-ing``, ``-ed``, plural ``-s``) is deliberately crude: it is applied
    identically to questions and passages, so "yellowing" meets "yellow" and
    "watered" meets "watering" without a stemming dependency.
    """

    tokens = []
    for token in _TOKEN_RE.findall(text.lower()):
        if token in STOPWORDS or len(token) < 2:
            continue
        if len(token) > 5 and token.endswith("ing"):
            token = token[:-3]
        elif len(token) > 4 and token.endswith("ed"):
            token = token[:-2]
        if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
            token = token[:-1]
        tokens.append(token)
    return tokens


class BM25:
    def __init__(self, documents: list[list[str]], k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.documents = documents
        self.lengths = [len(d) for d in documents]
        self.avg_length = (sum(self.lengths) / len(documents)) if documents else 0.0
        self.frequencies = [Counter(d) for d in documents]
        document_frequency: Counter = Counter()
        for counts in self.frequencies:
            document_frequency.update(counts.keys())
        n = len(documents)
        self.idf = {
            term: math.log(1 + (n - df + 0.5) / (df + 0.5)) for term, df in document_frequency.items()
        }

    def score(self, query: list[str], index: int) -> float:
        counts = self.frequencies[index]
        length = self.lengths[index]
        total = 0.0
        for term in query:
            tf = counts.get(term)
            if not tf:
                continue
            idf = self.idf.get(term, 0.0)
            denominator = tf + self.k1 * (1 - self.b + self.b * length / (self.avg_length or 1))
            total += idf * tf * (self.k1 + 1) / denominator
        return total


def coverage(query: list[str], document: list[str]) -> float:
    """Fraction of distinct query terms that appear in the passage."""

    wanted = set(query)
    if not wanted:
        return 0.0
    return len(wanted & set(document)) / len(wanted)


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


@dataclass
class Candidate:
    chunk: Chunk
    lexical: float  # BM25 normalised by the best BM25 score of this query
    coverage: float  # 0..1
    similarity: float | None  # dense cosine, when available
    score: float  # combined relevance, 0..1

    @property
    def relevant(self) -> bool:
        return self._relevant

    _relevant: bool = False


@dataclass
class Retrieval:
    candidates: list[Candidate]  # relevant ones, best first, at most top_k
    mode: str  # "lexical" | "hybrid"
    considered: int  # passages scored
    query_terms: list[str]


def retrieve(
    question: str,
    chunks: list[Chunk],
    *,
    top_k: int,
    min_coverage: float,
    min_similarity: float,
    query_embedding: list[float] | None = None,
) -> Retrieval:
    """Rank `chunks` for `question` and keep those that pass the relevance gate.

    The gate is what turns "nothing relevant" into an explicit insufficient-context
    answer: a passage must either share enough of the question's terms
    (`coverage >= min_coverage`) or, when embeddings exist for both sides, be
    semantically close (`similarity >= min_similarity`).
    """

    terms = tokenize(question)
    if not chunks or not terms:
        return Retrieval([], "lexical", len(chunks), terms)

    documents = [tokenize(f"{c.title} {c.text}") for c in chunks]
    # Correct only close misspellings of names in this corpus, not arbitrary facts.
    vocabulary = {term for doc in documents for term in doc}
    names = sorted({term for c in chunks for term in tokenize(c.title.split(" — ")[0])})
    corrected = []
    for term in terms:
        matches = get_close_matches(term, names, n=2, cutoff=0.84) if len(term) >= 5 and term not in vocabulary else []
        corrected.append(matches[0] if len(matches) == 1 else term)
    # A second word can be corrected more leniently when its paired name is known.
    for title in (tokenize(c.title.split(" — ")[0]) for c in chunks):
        if len(title) == 2 and set(title) & set(corrected):
            for i, term in enumerate(corrected):
                if len(term) >= 5 and term not in vocabulary:
                    match = get_close_matches(term, title, n=1, cutoff=.75)
                    if match:
                        corrected[i] = match[0]
    terms = corrected
    bm25 = BM25(documents)
    raw = [bm25.score(terms, i) for i in range(len(chunks))]
    best = max(raw) or 1.0

    dense = query_embedding is not None and any(c.embedding for c in chunks)
    mode = "hybrid" if dense else "lexical"

    candidates: list[Candidate] = []
    for i, chunk in enumerate(chunks):
        lexical = raw[i] / best
        cover = coverage(terms, documents[i])
        similarity = None
        if dense and chunk.embedding:
            similarity = max(0.0, cosine(query_embedding, chunk.embedding))
        if similarity is None:
            score = 0.6 * cover + 0.4 * lexical
        else:
            score = 0.4 * cover + 0.2 * lexical + 0.4 * similarity
        candidate = Candidate(chunk, round(lexical, 4), round(cover, 4), similarity, round(score, 4))
        candidate._relevant = cover >= min_coverage or (
            similarity is not None and similarity >= min_similarity
        )
        candidates.append(candidate)

    relevant = [c for c in candidates if c.relevant and c.score > 0]
    # A named problem question should use its guide, not plants merely listing it.
    named_guides = [c for c in relevant if c.chunk.source == "almanac"
                    and c.chunk.title.endswith((" — disease reference", " — pest reference"))
                    and set(tokenize(c.chunk.title.split(" — ")[0])).issubset(set(terms))]
    named_plants = [c for c in relevant if c.chunk.title.endswith(" — plant reference")
                    and set(tokenize(c.chunk.title.split(" — ")[0])).issubset(set(terms))]
    if named_guides and not named_plants:
        relevant = named_guides
    relevant.sort(key=lambda c: (-c.score, c.chunk.chunk_id))
    return Retrieval(relevant[:top_k], mode, len(chunks), terms)

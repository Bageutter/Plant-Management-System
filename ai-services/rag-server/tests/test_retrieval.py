from __future__ import annotations

from retrieval import BM25, coverage, cosine, retrieve, tokenize
from store import Chunk

CHUNKS = [
    Chunk("health", "3", "summary", "Assessment #3 — Tomato, back bed",
          "Plant health assessment of Tomato, back bed. Status: at risk (health score 42/100). "
          "Summary: Lower-leaf yellowing with constantly wet soil suggests overwatering."),
    Chunk("health", "3", "recommendations", "Assessment #3 — Tomato, back bed",
          "Recommended actions for Tomato, back bed: Reduce watering (high priority): "
          "water only when the top 3cm of soil is dry."),
    Chunk("health", "1", "summary", "Assessment #1 — Basil, kitchen window",
          "Plant health assessment of Basil, kitchen window. Status: unhealthy. Summary: "
          "Extensive leaf damage consistent with pests, likely aphids."),
]


def test_tokenize_drops_stopwords_and_folds_plurals():
    assert tokenize("Why are the tomato's leaves turning yellow?") == ["tomato", "leave", "turn", "yellow"]
    assert tokenize("yellowing watered") == ["yellow", "water"]
    assert tokenize("the and of") == []
    assert "grass" in tokenize("grass")  # -ss words are not folded


def test_bm25_prefers_the_passage_with_more_query_terms():
    docs = [tokenize(c.text) for c in CHUNKS]
    index = BM25(docs)
    query = tokenize("tomato yellow leaves overwatering")
    scores = [index.score(query, i) for i in range(len(docs))]
    assert scores[0] > scores[1] > scores[2] >= 0
    assert coverage(query, docs[0]) > coverage(query, docs[2])


def test_retrieve_ranks_relevant_passages_and_gates_off_topic_questions():
    result = retrieve(
        "Why is the tomato in the back bed yellow?",
        CHUNKS,
        top_k=5,
        min_coverage=0.34,
        min_similarity=0.45,
    )
    assert result.mode == "lexical" and result.considered == 3
    assert result.candidates[0].chunk.chunk_id == "health:3:summary"
    assert all(c.chunk.source_id == "3" for c in result.candidates)  # basil does not pass the gate
    assert 0 < result.candidates[0].score <= 1

    off_topic = retrieve(
        "What is the capital of France?", CHUNKS, top_k=5, min_coverage=0.34, min_similarity=0.45
    )
    assert off_topic.candidates == []

    stopwords_only = retrieve("the and of", CHUNKS, top_k=5, min_coverage=0.34, min_similarity=0.45)
    assert stopwords_only.candidates == [] and stopwords_only.query_terms == []


def test_retrieve_respects_top_k_and_deterministic_ordering():
    result = retrieve("tomato back bed", CHUNKS, top_k=1, min_coverage=0.1, min_similarity=0.45)
    assert len(result.candidates) == 1


def test_hybrid_mode_uses_embeddings_when_both_sides_have_them():
    embedded = [
        Chunk(c.source, c.source_id, c.part, c.title, c.text, embedding=vec)
        for c, vec in zip(CHUNKS, ([1.0, 0.0], [0.9, 0.1], [0.0, 1.0]))
    ]
    # Semantically close to the basil passage but sharing no words with it.
    result = retrieve(
        "pest damage on herbs",
        embedded,
        top_k=5,
        min_coverage=0.34,
        min_similarity=0.45,
        query_embedding=[0.0, 1.0],
    )
    assert result.mode == "hybrid"
    assert [c.chunk.chunk_id for c in result.candidates] == ["health:1:summary"]
    assert result.candidates[0].similarity == 1.0

    assert cosine([1, 0], [0, 1]) == 0.0 and round(cosine([1, 1], [1, 1]), 6) == 1.0
    assert cosine([], [1.0]) == 0.0


def test_comparison_and_name_typos_still_retrieve_without_admitting_unrelated_queries():
    chunks = [
        Chunk("almanac", "basil", "reference", "Basil — plant reference", "Basil needs full sun."),
        Chunk("almanac", "zucchini", "reference", "Zucchini — plant reference", "Zucchini needs full sun."),
        Chunk("almanac", "mildew", "reference", "Powdery mildew — disease reference", "Improve airflow to prevent powdery mildew."),
    ]
    def search(question):
        return retrieve(question, chunks, top_k=5, min_coverage=.34, min_similarity=.45)
    assert {c.chunk.source_id for c in search("Compare basil and zucchini").candidates} == {"basil", "zucchini"}
    for question in ("powdery mildew", "powedery mildrew", "what prevent powedery mildren", "how do i deal with powdery mildrew"):
        assert search(question).candidates[0].chunk.source_id == "mildew"
    assert not search("What is the orbital period of Neptune?").candidates

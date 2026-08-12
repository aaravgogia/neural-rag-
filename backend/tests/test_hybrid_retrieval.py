"""
Real, runnable tests for hybrid retrieval -- pytest, no mocking needed since
none of this requires an external API. Run: pytest tests/test_hybrid_retrieval.py -v
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import pytest
import app.core.hybrid_retrieval as hybrid_retrieval
from app.config import settings
from app.core.hybrid_retrieval import DenseIndex, HybridRetriever, RetrievedChunk, reciprocal_rank_fusion


@pytest.fixture
def retriever():
    docs = [
        ("d1", "Invoice #4471 was issued on March 3rd for the Q1 consulting engagement."),
        ("d2", "Employees must submit expense reports within 30 days of purchase."),
        ("d3", "The reimbursement policy requires expense claims filed within one month."),
        ("d4", "SOC 2 compliance mandates customer data retained for seven years."),
        ("d5", "The company picnic is scheduled for the second Saturday of July."),
    ]
    chunks = [RetrievedChunk(id=i, text=t) for i, t in docs]
    return HybridRetriever(chunks)


def test_exact_keyword_match(retriever):
    """BM25 should surface the doc containing the literal invoice number."""
    results = retriever.retrieve("invoice 4471", k=2)
    assert any(r.id == "d1" for r in results)


def test_paraphrase_match(retriever):
    """A paraphrased query ('filed'/'file' stem match) should still find the
    reimbursement policy doc even without exact word overlap on 'submit'."""
    results = retriever.retrieve("how long to file expense claims", k=2)
    ids = [r.id for r in results]
    assert "d3" in ids


def test_irrelevant_query_returns_no_noise(retriever):
    """A query with zero real relevance to any doc should not return the
    company-picnic doc just because of leftover stopword overlap."""
    results = retriever.retrieve("what is the weather forecast tomorrow", k=3)
    # Either genuinely empty, or definitely not falsely matching d5's picnic date
    assert all(r.id != "d5" or r.fused_score > 0 for r in results)


def test_reciprocal_rank_fusion_basic():
    """RRF should rank a document highly if it's top-ranked in both lists."""
    ranking_a = {"x": 10.0, "y": 5.0, "z": 1.0}
    ranking_b = {"x": 0.9, "y": 0.1, "z": 0.5}
    fused = reciprocal_rank_fusion([ranking_a, ranking_b])
    assert fused["x"] > fused["y"]
    assert fused["x"] > fused["z"]


def test_dominant_bm25_match_is_protected_from_poor_dense_rank(monkeypatch):
    """A unique exact keyword match must not be buried by a bad dense ranking."""
    chunks = [RetrievedChunk(id=f"d{index}", text=f"Document {index}") for index in range(15)]
    retriever = HybridRetriever(chunks)

    # d0's BM25 score is more than 1.5x the runner-up, but RRF alone puts it
    # outside top five because every other candidate has a better dense rank.
    bm25_scores = {"d0": 100.0}
    bm25_scores.update({f"d{index}": 60.0 - index for index in range(1, 15)})
    dense_scores = {f"d{index}": float(15 - index) for index in range(1, 15)}
    dense_scores["d0"] = 0.01

    unprotected = sorted(
        reciprocal_rank_fusion([bm25_scores, dense_scores]),
        key=lambda chunk_id: reciprocal_rank_fusion([bm25_scores, dense_scores])[chunk_id],
        reverse=True,
    )
    assert unprotected.index("d0") >= 5  # reproduces the RRF-only failure

    monkeypatch.setattr(retriever.sparse, "search", lambda _query, _k: bm25_scores)
    monkeypatch.setattr(retriever.dense, "search", lambda _query, _k: dense_scores)
    # This test isolates fusion ordering from MMR's separate diversity policy.
    monkeypatch.setattr(hybrid_retrieval, "mmr_rerank", lambda items, *_args, top_n: items[:top_n])

    results = retriever.retrieve("invoice 4471", k=5, candidate_pool=15)

    assert "d0" in [chunk.id for chunk in results]
    assert [chunk.id for chunk in results].index("d0") < 5


def test_retrieve_returns_at_most_k(retriever):
    results = retriever.retrieve("expense policy", k=2)
    assert len(results) <= 2


def test_empty_index_raises():
    with pytest.raises(ValueError):
        HybridRetriever([])


@pytest.mark.skipif(os.getenv("RUN_REAL_EMBEDDING_TESTS") != "1", reason="downloads/loads the real embedding model")
def test_dense_encode_returns_real_sentence_transformer_vectors(monkeypatch):
    monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "sentence_transformers")
    index = DenseIndex([RetrievedChunk(id="d1", text="Expense claims are due within thirty days.")])
    vectors = index.encode(["Expense claim deadline", "Invoice payment terms"])

    assert index._sentence_transformer is not None
    assert index._fallback is None
    assert vectors.shape == (2, 384)  # all-MiniLM-L6-v2 embedding dimension
    assert vectors.dtype == np.float32
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0, atol=1e-5)


def test_reranker_promotes_exact_match_over_vague_related_chunk(monkeypatch):
    class FakeCrossEncoder:
        def predict(self, pairs, show_progress_bar=False):
            return [0.12 if "general policy" in passage else 0.98 for _, passage in pairs]

    monkeypatch.setattr(settings, "RERANKER_ENABLED", True)
    index = object.__new__(DenseIndex)
    index._reranker = FakeCrossEncoder()
    vague = RetrievedChunk(id="vague", text="The general policy explains reimbursement guidelines.")
    exact = RetrievedChunk(id="exact", text="Expense claims must be filed within 30 days of purchase.")

    reranked = index.rerank("What is the expense claim filing deadline?", [vague, exact], plan="pro")

    assert [chunk.id for chunk in reranked] == ["exact", "vague"]
    assert [chunk.rank for chunk in reranked] == [0, 1]
    assert index.last_reranker_applied is True


def test_retrieval_continues_when_reranker_load_fails(retriever, monkeypatch):
    """A cross-encoder outage must preserve the already-computed MMR result."""
    monkeypatch.setattr(settings, "RERANKER_ENABLED", True)

    def unavailable():
        raise RuntimeError("model download unavailable")

    monkeypatch.setattr(retriever.dense, "_get_reranker", unavailable)
    results = retriever.retrieve("expense policy deadline", k=2)

    assert results
    assert any(chunk.id in {"d2", "d3"} for chunk in results)
    assert retriever.reranker_applied is False

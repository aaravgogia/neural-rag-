"""
Hybrid retrieval engine: BM25 (sparse/lexical) + semantic embeddings
fused via Reciprocal Rank Fusion, followed by MMR re-ranking for diversity.

Why hybrid: pure vector search misses exact keyword/ID/number matches
(e.g. "invoice #4471", error codes, product SKUs). Pure BM25 misses
paraphrases and synonyms. Fusing both rankings is standard practice in
production RAG systems (this is the same idea behind Weaviate/Elasticsearch
"hybrid search" and Cohere's rerank pipeline).

The dense side is provider-backed: sentence-transformers is the default,
and OpenAI embeddings are selected with EMBEDDING_PROVIDER=openai.
"""
import math
import logging
from importlib.util import find_spec
from dataclasses import dataclass, field
from typing import List, Dict, Optional

import numpy as np
from rank_bm25 import BM25Okapi
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, HashingVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from nltk.stem import PorterStemmer

logger = logging.getLogger(__name__)
_stemmer = PorterStemmer()

# RRF intentionally ignores raw score magnitudes.  That is normally its
# strength, but a uniquely dominant lexical match (an invoice number, error
# code, or exact policy clause) deserves a small rank-protection exception.
# These are deliberately narrow guardrails, not global BM25 weights.
BM25_DOMINANCE_RATIO = 1.5
BM25_DOMINANCE_TOP_N = 5


def embedding_runtime_status() -> str:
    """Describe the selected dense backend without loading its model."""
    from app.config import settings

    provider = settings.EMBEDDING_PROVIDER.strip().lower()
    if provider == "openai":
        if not settings.OPENAI_API_KEY:
            return "HashingVectorizer fallback (EMBEDDING_PROVIDER=openai but OPENAI_API_KEY is missing)"
        if not find_spec("langchain_openai"):
            return "HashingVectorizer fallback (langchain-openai is not installed)"
        return f"OpenAIEmbeddings (real; {settings.EMBEDDING_MODEL}, lazy loaded)"
    if provider in {"", "sentence_transformers", "sentence-transformers"}:
        if not find_spec("sentence_transformers"):
            return "HashingVectorizer fallback (sentence-transformers is not installed)"
        return f"SentenceTransformer (real; {settings.SENTENCE_TRANSFORMER_MODEL}, lazy loaded)"
    if provider == "hashing":
        return "HashingVectorizer (lightweight configured backend)"
    return f"HashingVectorizer fallback (unsupported EMBEDDING_PROVIDER={provider!r})"


def reranker_runtime_status() -> str:
    """Describe the optional cross-encoder path without downloading it."""
    from app.config import settings

    if not settings.RERANKER_ENABLED:
        return "disabled (RERANKER_ENABLED=false)"
    if not find_spec("sentence_transformers"):
        return "disabled/fallback (sentence-transformers is not installed)"
    return f"CrossEncoder configured ({settings.RERANKER_MODEL}, lazy loaded; pro workspaces only)"


@dataclass
class RetrievedChunk:
    id: str
    text: str
    metadata: dict = field(default_factory=dict)
    bm25_score: float = 0.0
    dense_score: float = 0.0
    fused_score: float = 0.0
    rank: int = 0


def _tokenize(text: str) -> List[str]:
    # Stopword removal matters a lot for BM25 on small corpora: without it,
    # common words like "is"/"to"/"the" can get inflated IDF weight purely
    # from the tiny sample size and start dominating scores over the actual
    # content words. Reusing sklearn's stopword list keeps this dependency-free.
    #
    # Stemming closes (part of) the gap between BM25/TF-IDF and real semantic
    # embeddings: "expenses"/"expense", "filed"/"file", "submitting"/"submit"
    # all collapse to the same root, so exact-token matching stops failing on
    # simple morphological variation. It does NOT solve true synonymy
    # ("reimbursement" vs "expense claim") -- that's still a real embedding's job.
    return [
        _stemmer.stem(t)
        for t in text.lower().split()
        if t not in ENGLISH_STOP_WORDS
    ]


class SparseIndex:
    """BM25 lexical index -- exact term / keyword matching."""

    def __init__(self, chunks: List[RetrievedChunk]):
        self.chunks = chunks
        corpus = [_tokenize(c.text) for c in chunks]
        self.bm25 = BM25Okapi(corpus)

    def search(self, query: str, k: int) -> Dict[str, float]:
        scores = self.bm25.get_scores(_tokenize(query))
        # Drop zero-score docs -- BM25 returns a score for every doc in the
        # corpus, but a 0 means "no term overlap at all". Letting those into
        # RRF fusion lets irrelevant docs earn rank-based credit purely from
        # tie-breaking order, which corrupts fusion on small corpora.
        ranked = sorted(
            ((c, s) for c, s in zip(self.chunks, scores) if s > 0),
            key=lambda x: x[1], reverse=True
        )[:k]
        return {c.id: float(s) for c, s in ranked}


class DenseIndex:
    """Semantic embedding index, with an offline non-TF-IDF safety fallback."""

    def __init__(self, chunks: List[RetrievedChunk]):
        self.chunks = chunks
        self._fallback = None
        self._sentence_transformer = None
        self._reranker = None
        # Exposed to observability callers after each retrieval.  It is reset
        # on every rerank attempt so a previous successful request can never
        # make a later fallback look like it used the cross-encoder.
        self.last_reranker_applied = False
        self.matrix = self.encode([c.text for c in chunks])

    def _get_sentence_transformer(self):
        """Load the local embedding model once per index, on first use."""
        if self._sentence_transformer is None:
            from app.config import settings
            from sentence_transformers import SentenceTransformer
            self._sentence_transformer = SentenceTransformer(settings.SENTENCE_TRANSFORMER_MODEL)
        return self._sentence_transformer

    def _get_reranker(self):
        """Load the optional cross-encoder once per retrieval index."""
        if self._reranker is None:
            from app.config import settings
            from sentence_transformers import CrossEncoder
            self._reranker = CrossEncoder(settings.RERANKER_MODEL)
        return self._reranker

    def encode(self, texts: List[str]) -> np.ndarray:
        """Return L2-normalised vectors using the configured embedding provider."""
        from app.config import settings
        provider = settings.EMBEDDING_PROVIDER.strip().lower()
        try:
            if provider == "openai":
                if not settings.OPENAI_API_KEY:
                    raise RuntimeError("OPENAI_API_KEY is required for EMBEDDING_PROVIDER=openai")
                from langchain_openai import OpenAIEmbeddings
                vectors = OpenAIEmbeddings(model=settings.EMBEDDING_MODEL, api_key=settings.OPENAI_API_KEY).embed_documents(texts)
                return self._normalise(np.asarray(vectors, dtype=np.float32))
            if provider in {"", "sentence_transformers", "sentence-transformers"}:
                model = self._get_sentence_transformer()
                return self._normalise(np.asarray(model.encode(texts, convert_to_numpy=True, show_progress_bar=False), dtype=np.float32))
            if provider == "hashing":
                if self._fallback is None:
                    self._fallback = HashingVectorizer(n_features=384, alternate_sign=False, norm="l2", tokenizer=_tokenize, token_pattern=None, lowercase=False)
                return self._fallback.transform(texts).toarray().astype(np.float32)
            raise RuntimeError(f"Unsupported EMBEDDING_PROVIDER: {provider}")
        except Exception as error:
            # The public demo deliberately remains zero-download/zero-key.
            # Hashing is only a boot-safe fallback; production should install
            # sentence-transformers or configure a valid OpenAI key.
            logger.warning("Semantic embedding backend unavailable (%s); using offline hashing fallback", error)
            if self._fallback is None:
                self._fallback = HashingVectorizer(n_features=384, alternate_sign=False, norm="l2", tokenizer=_tokenize, token_pattern=None, lowercase=False)
            return self._fallback.transform(texts).toarray().astype(np.float32)

    @staticmethod
    def _normalise(vectors: np.ndarray) -> np.ndarray:
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        return vectors / np.maximum(norms, 1e-12)

    def search(self, query: str, k: int) -> Dict[str, float]:
        query_vec = self.encode([query])
        sims = cosine_similarity(query_vec, self.matrix).flatten()
        # Same reasoning as SparseIndex: exclude true zero-similarity docs
        # (no shared vocabulary at all) from the ranking passed to RRF.
        ranked = sorted(
            ((c, s) for c, s in zip(self.chunks, sims) if s > 1e-9),
            key=lambda x: x[1], reverse=True
        )[:k]
        return {c.id: float(s) for c, s in ranked}

    def rerank(self, query: str, chunks: List[RetrievedChunk], plan: str = "free") -> List[RetrievedChunk]:
        """Optionally apply a precise cross-encoder score after MMR selection."""
        from app.config import settings

        self.last_reranker_applied = False
        if plan != "pro" or not settings.RERANKER_ENABLED or len(chunks) < 2:
            return chunks
        try:
            scores = self._get_reranker().predict(
                [(query, chunk.text) for chunk in chunks],
                show_progress_bar=False,
            )
            reranked = [chunk for _, chunk in sorted(zip(scores, chunks), key=lambda item: float(item[0]), reverse=True)]
            for rank, chunk in enumerate(reranked):
                chunk.rank = rank
            self.last_reranker_applied = True
            return reranked
        except Exception as error:
            logger.warning("Cross-encoder reranker unavailable (%s); using MMR ordering", error)
            return chunks


def reciprocal_rank_fusion(
    rankings: List[Dict[str, float]], k: int = 60
) -> Dict[str, float]:
    """
    Standard RRF: score(d) = sum over rankers of 1 / (k + rank_in_that_ranker(d))
    Robust to wildly different score scales between BM25 and cosine similarity --
    which is exactly why you can't just average raw scores from different methods.
    """
    fused: Dict[str, float] = {}
    for ranking in rankings:
        sorted_ids = sorted(ranking.keys(), key=lambda i: ranking[i], reverse=True)
        for rank, doc_id in enumerate(sorted_ids):
            fused[doc_id] = fused.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
    return fused


def protect_dominant_bm25_match(
    candidate_ids: List[str],
    bm25_scores: Dict[str, float],
    dominance_ratio: float = BM25_DOMINANCE_RATIO,
    top_n: int = BM25_DOMINANCE_TOP_N,
) -> List[str]:
    """Keep one unambiguous lexical winner within the fused top ``top_n``.

    RRF deliberately uses ranks rather than raw score scale.  Consequently a
    chunk whose BM25 score is far above every other candidate can still fall
    behind several mediocre chunks if its dense rank is poor (notably with an
    offline hashing encoder).  We only adjust that single exceptional case:
    the strongest positive BM25 score must be at least ``dominance_ratio``
    times the runner-up.  Ordinary BM25 rankings, including paraphrase-heavy
    queries, remain entirely governed by regular RRF and MMR.
    """
    if len(candidate_ids) < 2 or len(bm25_scores) < 2 or top_n <= 0:
        return candidate_ids

    ranked_bm25 = sorted(bm25_scores.items(), key=lambda item: item[1], reverse=True)
    dominant_id, dominant_score = ranked_bm25[0]
    _, next_score = ranked_bm25[1]
    if (
        dominant_score <= 0
        or next_score <= 0
        or dominant_score < next_score * dominance_ratio
        or dominant_id not in candidate_ids
    ):
        return candidate_ids

    current_rank = candidate_ids.index(dominant_id)
    protected_rank = min(top_n - 1, len(candidate_ids) - 1)
    if current_rank <= protected_rank:
        return candidate_ids

    protected = list(candidate_ids)
    protected.pop(current_rank)
    protected.insert(protected_rank, dominant_id)
    logger.info(
        "Protected dominant BM25 match %s from fused rank %s to rank %s "
        "(%.4f vs runner-up %.4f)",
        dominant_id,
        current_rank + 1,
        protected_rank + 1,
        dominant_score,
        next_score,
    )
    return protected


def mmr_rerank(
    chunks: List[RetrievedChunk],
    query_vec: np.ndarray,
    doc_vecs: np.ndarray,
    lambda_mult: float = 0.6,
    top_n: int = 5,
) -> List[RetrievedChunk]:
    """
    Maximal Marginal Relevance: greedily picks the next chunk that maximizes
    (lambda * relevance_to_query) - ((1-lambda) * max_similarity_to_already_picked).
    Prevents returning 5 near-duplicate chunks from the same paragraph --
    a real failure mode of naive top-k vector search.
    """
    if len(chunks) == 0:
        return []
    selected: List[int] = []
    candidates = list(range(len(chunks)))

    relevance = cosine_similarity(query_vec, doc_vecs).flatten()

    while candidates and len(selected) < top_n:
        if not selected:
            best = max(candidates, key=lambda i: relevance[i])
        else:
            def mmr_score(i):
                diversity_penalty = max(
                    cosine_similarity(doc_vecs[i:i+1], doc_vecs[j:j+1])[0][0]
                    for j in selected
                )
                return lambda_mult * relevance[i] - (1 - lambda_mult) * diversity_penalty
            best = max(candidates, key=mmr_score)
        selected.append(best)
        candidates.remove(best)

    return [chunks[i] for i in selected]


class HybridRetriever:
    """Public interface: index once, query many times."""

    def __init__(self, chunks: List[RetrievedChunk]):
        if not chunks:
            raise ValueError("HybridRetriever needs at least one chunk to index")
        self.chunks = chunks
        self.by_id = {c.id: c for c in chunks}
        self.sparse = SparseIndex(chunks)
        self.dense = DenseIndex(chunks)

    @property
    def reranker_applied(self) -> bool:
        """Whether the most recent retrieval completed cross-encoder reranking."""
        return self.dense.last_reranker_applied

    def retrieve(self, query: str, k: int = 5, candidate_pool: int = 20, plan: str = "free", dense_query: str | None = None) -> List[RetrievedChunk]:
        bm25_scores = self.sparse.search(query, candidate_pool)
        dense_scores = self.dense.search(dense_query or query, candidate_pool)

        fused = reciprocal_rank_fusion([bm25_scores, dense_scores])
        candidate_ids = sorted(fused.keys(), key=lambda i: fused[i], reverse=True)[:candidate_pool]
        candidate_ids = protect_dominant_bm25_match(candidate_ids, bm25_scores)

        results = []
        for rank, doc_id in enumerate(candidate_ids):
            c = self.by_id[doc_id]
            c.bm25_score = bm25_scores.get(doc_id, 0.0)
            c.dense_score = dense_scores.get(doc_id, 0.0)
            c.fused_score = fused[doc_id]
            c.rank = rank
            results.append(c)

        if len(results) > k:
            query_vec = self.dense.encode([query])
            doc_indices = [self.chunks.index(c) for c in results]
            doc_vecs = self.dense.matrix[doc_indices]
            results = mmr_rerank(results, query_vec, doc_vecs, top_n=k)

        return self.dense.rerank(query, results, plan=plan)

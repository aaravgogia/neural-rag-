"""
Semantic query cache: caches by MEANING, not exact string match.

A naive cache keyed on the literal query string misses obvious repeats like
"what's the refund policy" vs "what is your refund policy" vs "refund policy?"
-- three different strings, same question, same expensive LLM+retrieval call
three times. This cache uses cosine similarity over TF-IDF vectors (same
zero-API-key design as hybrid_retrieval.py) to catch near-duplicate queries
and serve a cached answer instead of recomputing.

In production, swap the TF-IDF vectorizer for real query embeddings; the
threshold-based lookup logic is unchanged.
"""
import time
import logging
import re
from dataclasses import dataclass
from typing import Optional, List, Tuple

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

logger = logging.getLogger(__name__)


def _numeric_tokens(text: str) -> set[str]:
    """Return literal numeric identifiers contained in a query.

    Numeric tokens are often identifiers (invoice, order, ticket, account),
    where substituting one value for another must never reuse a cached answer.
    """
    return set(re.findall(r"\d+", text))


@dataclass
class CacheEntry:
    query: str
    answer: dict
    embedding_row: int
    created_at: float
    hits: int = 0


class SemanticCache:
    def __init__(self, similarity_threshold: float = 0.86, ttl_seconds: int = 3600, max_entries: int = 500):
        self.similarity_threshold = similarity_threshold
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self.entries: List[CacheEntry] = []
        self._vectorizer: Optional[TfidfVectorizer] = None
        self._matrix = None

    def _rebuild_index(self):
        """TF-IDF needs the full corpus to fit; rebuild on writes. For <500
        entries at chat-cache scale this is sub-millisecond, not a real cost."""
        if not self.entries:
            self._vectorizer = None
            self._matrix = None
            return
        self._vectorizer = TfidfVectorizer(stop_words="english")
        self._matrix = self._vectorizer.fit_transform([e.query for e in self.entries])

    def _evict_expired(self):
        now = time.time()
        before = len(self.entries)
        self.entries = [e for e in self.entries if now - e.created_at < self.ttl_seconds]
        if len(self.entries) != before:
            self._rebuild_index()

    def lookup(self, query: str) -> Tuple[Optional[dict], float]:
        """Returns (cached_answer_or_None, similarity_score)."""
        self._evict_expired()
        if not self.entries or self._vectorizer is None:
            return None, 0.0

        query_vec = self._vectorizer.transform([query])
        sims = cosine_similarity(query_vec, self._matrix).flatten()
        best_idx = int(sims.argmax())
        best_score = float(sims[best_idx])

        if best_score >= self.similarity_threshold:
            entry = self.entries[best_idx]
            if _numeric_tokens(query) != _numeric_tokens(entry.query):
                logger.info(
                    "Semantic cache numeric-token mismatch; treating as miss: %r != %r",
                    query,
                    entry.query,
                )
                return None, best_score
            entry.hits += 1
            logger.info(f"Semantic cache HIT ({best_score:.3f}): {query!r} ~= {entry.query!r}")
            return entry.answer, best_score

        return None, best_score

    def store(self, query: str, answer: dict):
        if len(self.entries) >= self.max_entries:
            # Evict least-recently-added (simple FIFO; LRU by hit-count is a
            # reasonable upgrade but adds complexity this cache size doesn't need)
            self.entries.pop(0)
        self.entries.append(CacheEntry(query=query, answer=answer, embedding_row=len(self.entries), created_at=time.time()))
        self._rebuild_index()

    def stats(self) -> dict:
        return {
            "entries": len(self.entries),
            "total_hits": sum(e.hits for e in self.entries),
            "threshold": self.similarity_threshold,
        }

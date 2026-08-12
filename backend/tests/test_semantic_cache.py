import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.semantic_cache import SemanticCache


def test_exact_query_hits_cache():
    cache = SemanticCache(similarity_threshold=0.5)
    cache.store("what is the refund policy", {"answer": "30 days"})
    result, score = cache.lookup("what is the refund policy")
    assert result is not None
    assert score > 0.99


def test_paraphrase_hits_cache_above_threshold():
    cache = SemanticCache(similarity_threshold=0.3)
    cache.store("what is your refund policy", {"answer": "30 days"})
    result, score = cache.lookup("what's the refund policy")
    assert result is not None


def test_different_numeric_identifiers_do_not_false_hit():
    cache = SemanticCache(similarity_threshold=0.1)
    cache.store("show the status of invoice 4471", {"answer": "paid"})

    result, score = cache.lookup("show the status of invoice 9982")

    assert score >= cache.similarity_threshold
    assert result is None
    assert cache.stats()["total_hits"] == 0


def test_paraphrases_without_numeric_tokens_still_hit():
    cache = SemanticCache(similarity_threshold=0.3)
    cache.store("what is your refund policy", {"answer": "30 days"})

    result, _ = cache.lookup("what's the refund policy")

    assert result == {"answer": "30 days"}


def test_unrelated_query_misses():
    cache = SemanticCache(similarity_threshold=0.5)
    cache.store("what is the refund policy", {"answer": "30 days"})
    result, score = cache.lookup("how do I reset my password")
    assert result is None
    assert score == 0.0


def test_empty_cache_always_misses():
    cache = SemanticCache()
    result, score = cache.lookup("anything at all")
    assert result is None
    assert score == 0.0


def test_ttl_expiry():
    cache = SemanticCache(similarity_threshold=0.5, ttl_seconds=0)
    cache.store("test query", {"answer": "x"})
    import time; time.sleep(0.01)
    result, score = cache.lookup("test query")
    assert result is None  # expired immediately due to ttl_seconds=0

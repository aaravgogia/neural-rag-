"""Compare hybrid retrieval quality with and without the optional reranker.

Run from backend/:
    python scripts/evaluate_hybrid_retrieval.py
"""
import json
import math
import os
import sys
import time
import ctypes
from ctypes import wintypes
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import settings
import app.core.hybrid_retrieval as hybrid_retrieval
from app.core.hybrid_retrieval import HybridRetriever, RetrievedChunk


DATASET_PATH = Path(__file__).resolve().parents[1] / "evals" / "hybrid_retrieval_labeled.json"


def working_set_bytes() -> int:
    """Return this process's RSS/working set without adding a runtime dependency."""
    if os.name != "nt":
        return 0

    class ProcessMemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.c_ulong),
            ("page_fault_count", ctypes.c_ulong),
            ("peak_working_set_size", ctypes.c_size_t),
            ("working_set_size", ctypes.c_size_t),
            ("quota_peak_paged_pool_usage", ctypes.c_size_t),
            ("quota_paged_pool_usage", ctypes.c_size_t),
            ("quota_peak_non_paged_pool_usage", ctypes.c_size_t),
            ("quota_non_paged_pool_usage", ctypes.c_size_t),
            ("pagefile_usage", ctypes.c_size_t),
            ("peak_pagefile_usage", ctypes.c_size_t),
        ]

    counters = ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessMemoryCounters), wintypes.DWORD]
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    if not psapi.GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
        raise ctypes.WinError(ctypes.get_last_error())
    return int(counters.working_set_size)


def reciprocal_rank(ranked_ids: list[str], relevant_ids: set[str]) -> float:
    for position, chunk_id in enumerate(ranked_ids, start=1):
        if chunk_id in relevant_ids:
            return 1.0 / position
    return 0.0


def ndcg_at_k(ranked_ids: list[str], relevant_ids: set[str], k: int = 5) -> float:
    dcg = sum(
        1.0 / math.log2(position + 1)
        for position, chunk_id in enumerate(ranked_ids[:k], start=1)
        if chunk_id in relevant_ids
    )
    ideal_count = min(k, len(relevant_ids))
    ideal_dcg = sum(1.0 / math.log2(position + 1) for position in range(1, ideal_count + 1))
    return dcg / ideal_dcg if ideal_dcg else 0.0


def evaluate(retriever: HybridRetriever, queries: list[dict]) -> dict:
    ndcgs, rrs = [], []
    details = []
    for item in queries:
        ranked_ids = [chunk.id for chunk in retriever.retrieve(item["query"], k=5)]
        relevant_ids = set(item["relevant_chunk_ids"])
        ndcgs.append(ndcg_at_k(ranked_ids, relevant_ids))
        rrs.append(reciprocal_rank(ranked_ids, relevant_ids))
        details.append({"query": item["query"], "ranked_ids": ranked_ids})
    return {
        "ndcg_at_5": sum(ndcgs) / len(ndcgs),
        "mrr": sum(rrs) / len(rrs),
        "queries": details,
    }


def main() -> None:
    dataset = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    retriever = HybridRetriever([RetrievedChunk(**chunk) for chunk in dataset["chunks"]])

    original = settings.RERANKER_ENABLED
    original_guard = hybrid_retrieval.protect_dominant_bm25_match
    reranker_error = None
    load_seconds = 0.0
    rerank_seconds = 0.0
    rss_before_load = working_set_bytes()
    rss_after_load = rss_before_load
    try:
        # Compare the lexical-signal safeguard directly against the prior
        # plain-RRF behaviour on the same labeled corpus.
        settings.RERANKER_ENABLED = False
        hybrid_retrieval.protect_dominant_bm25_match = lambda candidate_ids, _scores: list(candidate_ids)
        rrf_only = evaluate(retriever, dataset["queries"])
        hybrid_retrieval.protect_dominant_bm25_match = original_guard
        guarded = evaluate(retriever, dataset["queries"])

        settings.RERANKER_ENABLED = True
        try:
            load_started = time.perf_counter()
            retriever.dense._get_reranker()
            load_seconds = time.perf_counter() - load_started
            rss_after_load = working_set_bytes()
            rerank_started = time.perf_counter()
            reranked = evaluate(retriever, dataset["queries"])
            rerank_seconds = time.perf_counter() - rerank_started
        except Exception as error:
            # The production pipeline has the same graceful fallback.  An
            # evaluation should still produce its guarded-RRF metrics on a
            # laptop without a supported torch/model runtime.
            reranker_error = error
            reranked = guarded
    finally:
        settings.RERANKER_ENABLED = original
        hybrid_retrieval.protect_dominant_bm25_match = original_guard

    print("Hybrid retrieval labeled evaluation")
    print(f"RRF only  NDCG@5={rrf_only['ndcg_at_5']:.3f}  MRR={rrf_only['mrr']:.3f}")
    print(f"Guarded   NDCG@5={guarded['ndcg_at_5']:.3f}  MRR={guarded['mrr']:.3f}")
    print(f"Reranker  NDCG@5={reranked['ndcg_at_5']:.3f}  MRR={reranked['mrr']:.3f}")
    if reranker_error is None:
        print(
            "Cross-encoder load "
            f"{load_seconds:.3f}s; working-set delta={(rss_after_load - rss_before_load) / 1024 / 1024:.2f} MiB; "
            f"reranking {len(dataset['queries'])} queries={rerank_seconds:.3f}s"
        )
    else:
        print(f"Cross-encoder unavailable; reranker comparison uses guarded RRF fallback: {reranker_error}")
    for result in reranked["queries"]:
        print(f"- {result['query']}: {', '.join(result['ranked_ids'])}")


if __name__ == "__main__":
    main()

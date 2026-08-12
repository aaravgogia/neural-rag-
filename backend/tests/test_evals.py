import os
import sys
from datetime import datetime

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.api.routes.evals import summarize
from app.core.graph_agent_v2 import ObservableRAGAgent
from app.core.hybrid_retrieval import HybridRetriever, RetrievedChunk
from app.core.llm_provider import LLMProvider
from app.models.database import EvalMetric


class DeterministicProvider(LLMProvider):
    async def generate(self, prompt, stream=True):
        yield "Invoice 4471 covers consulting. "


@pytest.mark.asyncio
async def test_full_agent_run_writes_eval_record():
    written = []
    async def recorder(record):
        written.append(record)
    chunks = [RetrievedChunk(id="invoice", text="Invoice 4471 covers consulting.", metadata={"source": "invoice.pdf"})]
    agent = ObservableRAGAgent(HybridRetriever(chunks), llm_provider=DeterministicProvider(), eval_recorder=recorder)
    await agent.run_streaming("What does invoice 4471 cover?", namespace=None, session_id="session-1", user_id="user-1")
    assert len(written) == 1
    assert written[0]["session_id"] == "session-1"
    assert written[0]["user_id"] == "user-1"
    assert written[0]["latency_ms"] >= 0
    assert "generate_answer" in written[0]["node_timings"]


def test_summary_computes_quality_averages_and_latency_percentiles():
    records = [
        EvalMetric(session_id="a", query_text="a", groundedness=.6, retrieval_relevance=.4, latency_ms=100, cache_hit=False, timestamp=datetime.utcnow()),
        EvalMetric(session_id="b", query_text="b", groundedness=.8, retrieval_relevance=.6, latency_ms=300, cache_hit=True, timestamp=datetime.utcnow()),
        EvalMetric(session_id="c", query_text="c", groundedness=1, retrieval_relevance=.8, latency_ms=900, cache_hit=True, timestamp=datetime.utcnow()),
    ]
    result = summarize(records)
    assert result["avg_groundedness"] == .8
    assert result["avg_retrieval_relevance"] == .6
    assert result["cache_hit_rate"] == round(2 / 3, 3)
    assert result["p50_latency_ms"] == 300
    assert result["p95_latency_ms"] == 900

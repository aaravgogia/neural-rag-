import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from types import SimpleNamespace

from app.core.llm_provider import GeminiProvider, LLMProvider, StubProvider, get_llm_provider
from app.core.graph_agent_v2 import ObservableRAGAgent
from app.core.hybrid_retrieval import HybridRetriever, RetrievedChunk
from app.core.web_search_provider import WebSearchProvider, WebSearchResult


class FakeStreamingProvider(LLMProvider):
    async def generate(self, prompt: str, stream: bool = True):
        assert "Question:" in prompt
        for token in ("hello ", "world"):
            yield token

class FailingHyDEProvider(LLMProvider):
    async def generate(self, prompt: str, stream: bool = True):
        raise RuntimeError("provider unavailable")
        yield ""


@pytest.mark.asyncio
async def test_provider_streams_tokens_in_order():
    provider = FakeStreamingProvider()
    received = [token async for token in provider.generate("Question: test")]
    assert received == ["hello ", "world"]


@pytest.mark.asyncio
async def test_gemini_provider_streams_tokens_in_order_without_network():
    class FakeModels:
        def generate_content_stream(self, **kwargs):
            assert kwargs["model"] == "gemini-test-flash"
            assert kwargs["contents"] == "Question: test"

            async def stream():
                yield SimpleNamespace(text="Gemini ", usage_metadata=None)
                yield SimpleNamespace(text="answer", usage_metadata={"prompt_token_count": 2, "candidates_token_count": 2})

            return stream()

    client = SimpleNamespace(aio=SimpleNamespace(models=FakeModels()))
    provider = GeminiProvider("not-a-real-key", model="gemini-test-flash", client=client)
    received = [token async for token in provider.generate("Question: test")]

    assert received == ["Gemini ", "answer"]
    assert provider.last_usage().prompt_tokens == 2
    assert provider.last_usage().completion_tokens == 2


@pytest.mark.asyncio
async def test_stub_provider_is_a_streaming_fallback():
    provider = StubProvider()
    tokens = [token async for token in provider.generate("Context:\nExpense reports are due within 30 days.\n\nQuestion: when are expenses due?")]
    assert tokens
    assert "Expense" in "".join(tokens)


def test_auto_provider_falls_back_without_keys(monkeypatch):
    monkeypatch.setattr("app.core.llm_provider.settings.OPENAI_API_KEY", "")
    monkeypatch.setattr("app.core.llm_provider.settings.ANTHROPIC_API_KEY", "")
    monkeypatch.setattr("app.core.llm_provider.settings.MISTRAL_API_KEY", "")
    monkeypatch.setattr("app.core.llm_provider.settings.GEMINI_API_KEY", "")
    monkeypatch.setattr("app.core.llm_provider.settings.LLM_PROVIDER", "auto")
    assert isinstance(get_llm_provider(), StubProvider)


def test_auto_provider_selects_gemini_when_it_is_the_only_configured_key(monkeypatch):
    """Gemini must participate in ``auto`` instead of silently falling back."""
    monkeypatch.setattr("app.core.llm_provider.settings.OPENAI_API_KEY", "")
    monkeypatch.setattr("app.core.llm_provider.settings.ANTHROPIC_API_KEY", "")
    monkeypatch.setattr("app.core.llm_provider.settings.MISTRAL_API_KEY", "")
    monkeypatch.setattr("app.core.llm_provider.settings.GEMINI_API_KEY", "gemini-test-key")
    monkeypatch.setattr("app.core.llm_provider.settings.LLM_PROVIDER", "auto")

    class FakeGeminiProvider:
        def __init__(self, api_key):
            self.api_key = api_key

    monkeypatch.setattr("app.core.llm_provider.GeminiProvider", FakeGeminiProvider)
    provider = get_llm_provider()

    assert isinstance(provider, FakeGeminiProvider)
    assert provider.api_key == "gemini-test-key"

@pytest.mark.asyncio
async def test_hyde_failure_falls_back_to_raw_query(monkeypatch):
    monkeypatch.setattr("app.core.graph_agent_v2.settings.HYDE_ENABLED", True)
    agent = ObservableRAGAgent(HybridRetriever([RetrievedChunk(id="a", text="Invoice 4471 covers consulting.")]), llm_provider=FailingHyDEProvider())
    state = {"question": "What does invoice 4471 cover?", "session_id": "demo", "conversation_context": ""}
    result = await agent._analyze_query(state)
    assert result["hyde_query"] == ""


def test_citations_include_only_grounded_chunks_and_append_markers():
    agent = object.__new__(ObservableRAGAgent)
    chunks = [
        RetrievedChunk(id="doc-a", text="Invoice 4471 covers the Q1 consulting engagement.", metadata={"source": "invoices.pdf", "document_id": "invoice-doc", "chunk_index": 4, "source_page": 3}, fused_score=0.04),
        RetrievedChunk(id="doc-b", text="Employees submit expense reports within thirty days.", metadata={"source": "hr.pdf"}, fused_score=0.02),
    ]
    answer, citations = agent._attach_citations("Invoice 4471 covers the consulting engagement.", chunks)
    assert answer.endswith("[1]")
    assert len(citations) == 1
    assert citations[0] == {"doc_id": "invoice-doc", "doc_title": "invoices.pdf", "chunk_text": chunks[0].text, "chunk_index": 4, "source_page": 3, "score": 0.04, "source_type": "document"}


class LowConfidenceRetriever:
    def retrieve(self, query, k=4):
        return [RetrievedChunk(id="internal", text="Internal information is unrelated.", metadata={"source": "handbook.pdf"}, fused_score=.01)]


class FakeWebSearch(WebSearchProvider):
    configured = True
    async def search(self, query):
        return [WebSearchResult(title="External reference", content="External reference explains the answer clearly.", url="https://example.test/reference", score=.8)]


class RerankedRetriever:
    reranker_applied = True

    def retrieve(self, query, k=4):
        return [RetrievedChunk(id="deadline", text="Expense reports are due within thirty days.", fused_score=.8)]


class EmptyCache:
    def lookup(self, query):
        return None, 0.0

    def store(self, query, value):
        return None


class NoWebSearch:
    configured = False


@pytest.mark.asyncio
async def test_low_relevance_routes_to_web_search_fallback(monkeypatch):
    monkeypatch.setattr("app.core.graph_agent_v2.settings.RETRIEVAL_CONFIDENCE_THRESHOLD", .35)
    events = []
    async def recorder(record):
        return None
    agent = ObservableRAGAgent(LowConfidenceRetriever(), llm_provider=FakeStreamingProvider(), web_search_provider=FakeWebSearch(), eval_recorder=recorder)

    async def emit(event):
        events.append(event)

    await agent.run_streaming("What does the external reference say?", namespace=None, trace_cb=emit)
    assert any(event["type"] == "web_search" and event["status"] == "completed" for event in events)
    assert any(event["type"] == "node_start" and event["node"] == "web_search_fallback" for event in events)

    final_state = await agent.graph.ainvoke({
        "question": "Which source explains the result?", "original_question": "Which source explains the result?",
        "context_chunks": [], "answer": "", "needs_retrieval": True, "needs_improvement": False,
        "iteration": 0, "namespace": None, "cache_hit": False, "eval_metrics": {}, "web_search_attempted": False,
    })
    assert final_state["web_search_attempted"] is True
    assert any(chunk.metadata.get("source_type") == "external" for chunk in final_state["context_chunks"])


@pytest.mark.asyncio
async def test_retrieve_trace_reports_cross_encoder_reranking():
    events = []

    async def recorder(record):
        return None

    async def emit(event):
        events.append(event)

    agent = ObservableRAGAgent(
        RerankedRetriever(), cache=EmptyCache(), llm_provider=FakeStreamingProvider(),
        web_search_provider=NoWebSearch(), eval_recorder=recorder,
    )
    await agent.run_streaming("When are expense reports due?", namespace=None, trace_cb=emit)

    retrieve_end = next(event for event in events if event["type"] == "node_end" and event["node"] == "retrieve_documents")
    assert retrieve_end["result"]["reranking_applied"] is True

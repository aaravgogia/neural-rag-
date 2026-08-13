import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.rag_pipeline import RAGPipeline
from app.core.graph_agent import RAGGraphAgent


class _Document:
    page_content = "Mistral is the configured provider."
    metadata = {"source": "deployment.md", "document_id": "doc-1"}


class _VectorStore:
    async def similarity_search(self, **_kwargs):
        return [(_Document(), 0.9)]


class _MistralLikeProvider:
    async def generate(self, prompt, stream=True):
        assert "Mistral is the configured provider." in prompt
        yield "Provider answer"


@pytest.mark.asyncio
async def test_rag_pipeline_uses_injected_provider_not_openai():
    pipeline = RAGPipeline(_VectorStore(), llm_provider=_MistralLikeProvider())

    result = await pipeline.query("Which provider?", user_id="user-1", workspace_id="workspace-1")

    assert result["answer"] == "Provider answer"
    assert result["sources"][0]["document_id"] == "doc-1"


def test_legacy_graph_agent_uses_injected_provider_not_openai():
    """Regression: application startup must not require OPENAI_API_KEY."""
    agent = RAGGraphAgent(_VectorStore(), llm_provider=_MistralLikeProvider())

    assert agent.llm.__class__ is _MistralLikeProvider

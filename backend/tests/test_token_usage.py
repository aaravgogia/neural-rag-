import os
import sys
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.api.routes.analytics import summarize_costs
from app.core.graph_agent_v2 import ObservableRAGAgent
from app.core.llm_provider import StubProvider
from app.models.database import Base, TokenUsage
from app.core.hybrid_retrieval import RetrievedChunk


class OneChunkRetriever:
    reranker_applied = False

    def retrieve(self, query, k=4):
        return [RetrievedChunk(id="invoice", text="Invoice 4471 covers the consulting engagement.", fused_score=.8)]


class EmptyCache:
    def lookup(self, query):
        return None, 0.0

    def store(self, query, value):
        return None


class NoWebSearch:
    configured = False


@pytest.mark.asyncio
async def test_chat_run_persists_sane_token_usage(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'usage.db'}")
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async def usage_recorder(record):
        async with maker() as session:
            session.add(TokenUsage(**record))
            await session.commit()

    async def eval_recorder(record):
        return None

    agent = ObservableRAGAgent(
        OneChunkRetriever(), cache=EmptyCache(), llm_provider=StubProvider(),
        web_search_provider=NoWebSearch(), eval_recorder=eval_recorder,
        usage_recorder=usage_recorder,
    )
    await agent.run_streaming("What does invoice 4471 cover?", namespace=None, session_id="session-usage", user_id="user-usage")

    async with maker() as session:
        row = (await session.execute(select(TokenUsage))).scalar_one()
    await engine.dispose()

    assert row.user_id == "user-usage"
    assert row.session_id == "session-usage"
    assert row.prompt_tokens > 0
    assert row.completion_tokens > 0
    assert row.estimated_cost_usd == 0.0  # StubLLM never represents a paid call.


def test_cost_summary_is_user_day_ready():
    today = datetime.utcnow()
    records = [
        TokenUsage(user_id="u", session_id="s", prompt_tokens=100, completion_tokens=20, estimated_cost_usd=.001, created_at=today),
        TokenUsage(user_id="u", session_id="s", prompt_tokens=40, completion_tokens=10, estimated_cost_usd=.002, created_at=today - timedelta(days=1)),
    ]
    result = summarize_costs(records)
    assert result["total_requests"] == 2
    assert result["total_prompt_tokens"] == 140
    assert result["total_completion_tokens"] == 30
    assert result["total_cost_usd"] == .003
    assert len(result["daily"]) == 2

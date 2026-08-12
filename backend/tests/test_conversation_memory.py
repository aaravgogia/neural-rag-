import os
import sys
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.conversation_memory import ConversationContext, ConversationMemoryService
from app.core.graph_agent_v2 import ObservableRAGAgent
from app.core.hybrid_retrieval import RetrievedChunk
from app.core.llm_provider import LLMProvider
from app.models.database import Base, ChatMessage, ConversationMemory


class NoCache:
    def lookup(self, query):
        return None, 0.0

    def store(self, query, value):
        return None


class OneChunkRetriever:
    reranker_applied = False

    def retrieve(self, query, k=4):
        return [RetrievedChunk(id="invoice", text="Invoice 4471 covers the Q1 consulting engagement.", fused_score=.9)]


class NoWebSearch:
    configured = False


class FollowUpProvider(LLMProvider):
    def __init__(self):
        self.prompts = []

    async def generate(self, prompt, stream=True):
        self.prompts.append(prompt)
        if "What does invoice 4471 cover?" in prompt:
            yield "Last quarter refers to the Q1 consulting engagement."
        else:
            yield "I need the earlier conversation to resolve that reference."


class FixedMemory:
    def __init__(self, text):
        self.text = text

    async def load(self, conversation_id):
        return ConversationContext(text=self.text)


async def noop_recorder(record):
    return None


@pytest.mark.asyncio
async def test_follow_up_prompt_uses_prior_conversation_context():
    provider_without_memory = FollowUpProvider()
    no_history_agent = ObservableRAGAgent(
        OneChunkRetriever(), cache=NoCache(), llm_provider=provider_without_memory,
        web_search_provider=NoWebSearch(), memory_service=FixedMemory(""),
        eval_recorder=noop_recorder, usage_recorder=noop_recorder,
    )
    without_history = await no_history_agent.run_streaming("What about last quarter?", namespace=None, session_id="one")

    provider_with_memory = FollowUpProvider()
    history_agent = ObservableRAGAgent(
        OneChunkRetriever(), cache=NoCache(), llm_provider=provider_with_memory,
        web_search_provider=NoWebSearch(),
        memory_service=FixedMemory("Recent conversation:\nUser: What does invoice 4471 cover?\nAssistant: Invoice 4471 covers the Q1 consulting engagement."),
        eval_recorder=noop_recorder, usage_recorder=noop_recorder,
    )
    with_history = await history_agent.run_streaming("What about last quarter?", namespace=None, session_id="one")

    assert "earlier conversation" in without_history["answer"]
    assert "Q1 consulting" in with_history["answer"]
    assert "What does invoice 4471 cover?" in provider_with_memory.prompts[0]


@pytest.mark.asyncio
async def test_older_history_is_summarized_and_persisted(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'memory.db'}")
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with maker() as db:
        started = datetime.utcnow()
        db.add_all([
            ChatMessage(session_id="conversation-a", user_id="user", role="human", content="The Acme renewal is due in March.", created_at=started),
            ChatMessage(session_id="conversation-a", user_id="user", role="ai", content="I will remember the March Acme renewal.", created_at=started + timedelta(seconds=1)),
            ChatMessage(session_id="conversation-a", user_id="user", role="human", content="What is the current invoice status?", created_at=started + timedelta(seconds=2)),
            ChatMessage(session_id="conversation-a", user_id="user", role="ai", content="The invoice is pending approval.", created_at=started + timedelta(seconds=3)),
        ])
        await db.commit()

    memory = ConversationMemoryService(maker, recent_limit=2, token_budget=120)
    context = await memory.load("conversation-a")
    assert "Acme renewal is due in March" in context.text
    assert "current invoice status" in context.text
    async with maker() as db:
        row = (await db.execute(select(ConversationMemory).where(ConversationMemory.conversation_id == "conversation-a"))).scalar_one()
    await engine.dispose()
    assert row.summarized_message_count == 2
    assert "Acme renewal" in row.summary


@pytest.mark.asyncio
async def test_conversation_ids_do_not_leak_context(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'isolation.db'}")
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with maker() as db:
        db.add_all([
            ChatMessage(session_id="alpha", user_id="user", role="human", content="Alpha secret: project Orion."),
            ChatMessage(session_id="beta", user_id="user", role="human", content="Beta secret: project Atlas."),
        ])
        await db.commit()
    memory = ConversationMemoryService(maker, recent_limit=6, token_budget=200)
    alpha = await memory.load("alpha")
    beta = await memory.load("beta")
    await engine.dispose()
    assert "Orion" in alpha.text and "Atlas" not in alpha.text
    assert "Atlas" in beta.text and "Orion" not in beta.text

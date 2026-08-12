import os, sys
from datetime import datetime, timedelta
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.core.quotas import enforce_workspace_quota, workspace_usage
from app.models.database import Base, ChatSession, TokenUsage, Workspace

@pytest.mark.asyncio
async def test_workspace_quota_blocks_and_resets_next_month(monkeypatch, tmp_path):
    monkeypatch.setattr("app.core.quotas.settings.FREE_MONTHLY_TOKEN_QUOTA", 10)
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'q.db'}")
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as c: await c.run_sync(Base.metadata.create_all)
    now = datetime(2026, 8, 11)
    async with maker() as db:
        ws = Workspace(id="w", name="W", owner_id="u", plan="free")
        db.add_all([ws, ChatSession(id="s", user_id="u", workspace_id="w"), TokenUsage(session_id="s", user_id="u", prompt_tokens=10, completion_tokens=1, created_at=now)])
        await db.commit()
        with pytest.raises(Exception) as error: await enforce_workspace_quota(db, ws, now)
        assert getattr(error.value, "status_code", None) == 402
        assert error.value.detail["usage"]["tokens"] == 11
        assert (await workspace_usage(db, "w", now + timedelta(days=25)))["tokens"] == 0
    await engine.dispose()

def test_reranker_is_pro_only():
    from app.core.hybrid_retrieval import DenseIndex, RetrievedChunk
    index = object.__new__(DenseIndex); index.last_reranker_applied = False
    assert index.rerank("q", [RetrievedChunk(id="a", text="a"), RetrievedChunk(id="b", text="b")], plan="free")
    assert index.last_reranker_applied is False

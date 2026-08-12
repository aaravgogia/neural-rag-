import os
import sys
from datetime import datetime

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.api.routes import feedback
from app.api.routes.auth import get_current_user
from app.models.database import Base, ChatMessage, ChatSession, EvalMetric, Feedback, User, Workspace, WorkspaceMember, get_db


@pytest_asyncio.fixture
async def feedback_client(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'feedback.db'}")
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    owner = User(id="owner", email="owner@example.com", name="Owner")
    viewer = User(id="viewer", email="viewer@example.com", name="Viewer")
    workspace = Workspace(id="team", name="Team", owner_id=owner.id)
    session = ChatSession(id="session-1", user_id=viewer.id, workspace_id=workspace.id)
    answer = ChatMessage(id="answer-1", session_id=session.id, user_id=viewer.id, role="ai", content="Invoice 4471 covers consulting.", sources=[{"source": "invoice.pdf", "content": "Invoice 4471 covers consulting."}])
    metric = EvalMetric(id="eval-1", session_id=session.id, user_id=viewer.id, query_text="What does invoice 4471 cover?", groundedness=.9, retrieval_relevance=.8, latency_ms=10, timestamp=datetime.utcnow())
    async with maker() as db:
        db.add_all([owner, viewer, workspace, session, answer, metric,
                    WorkspaceMember(workspace_id=workspace.id, user_id=owner.id, role="owner"),
                    WorkspaceMember(workspace_id=workspace.id, user_id=viewer.id, role="viewer")])
        await db.commit()
    app = FastAPI()
    app.include_router(feedback.router, prefix="/api/v1")
    selected = {"user": viewer}

    async def override_db():
        async with maker() as db:
            yield db

    async def override_user():
        return selected["user"]

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://local") as client:
        yield client, selected, maker, {"owner": owner, "viewer": viewer}
    await engine.dispose()


@pytest.mark.asyncio
async def test_feedback_upsert_prevents_duplicate_rating(feedback_client):
    client, selected, maker, users = feedback_client
    body = {"message_id": "answer-1", "session_id": "session-1", "rating": "up"}
    created = await client.post("/api/v1/feedback", json=body)
    replaced = await client.post("/api/v1/feedback", json={**body, "rating": "down", "comment": "Missing detail"})
    assert created.status_code == 201
    assert replaced.status_code == 200
    assert replaced.json()["eval_metric_id"] == "eval-1"
    async with maker() as db:
        rows = (await db.execute(select(Feedback))).scalars().all()
    assert len(rows) == 1
    assert rows[0].rating == "down"
    assert rows[0].comment == "Missing detail"


@pytest.mark.asyncio
async def test_negative_feedback_queue_is_restricted_to_owner_or_admin(feedback_client):
    client, selected, maker, users = feedback_client
    await client.post("/api/v1/feedback", json={"message_id": "answer-1", "session_id": "session-1", "rating": "down"})
    denied = await client.get("/api/v1/feedback/negative")
    selected["user"] = users["owner"]
    allowed = await client.get("/api/v1/feedback/negative")
    assert denied.status_code == 403
    assert allowed.status_code == 200
    item = allowed.json()[0]
    assert item["groundedness"] == .9
    assert item["retrieved_chunks"][0]["source"] == "invoice.pdf"

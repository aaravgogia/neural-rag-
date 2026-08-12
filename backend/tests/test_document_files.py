import os
import sys

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.api.routes import documents
from app.api.routes.auth import get_current_user
from app.models.database import Base, Document, User, Workspace, WorkspaceMember, get_db


@pytest_asyncio.fixture
async def document_file_client(tmp_path):
    source_file = tmp_path / "invoice.txt"
    source_file.write_text("Invoice 4471 covers consulting.", encoding="utf-8")
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'files.db'}")
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    owner = User(id="owner", email="owner@example.com", name="Owner")
    outsider = User(id="outsider", email="outsider@example.com", name="Outsider")
    workspace = Workspace(id="team", name="Team", owner_id=owner.id)
    document = Document(id="invoice", user_id=owner.id, workspace_id=workspace.id, filename="invoice.txt", file_size=source_file.stat().st_size, file_type="txt", stored_path=str(source_file), status="done")
    async with maker() as db:
        db.add_all([owner, outsider, workspace, document, WorkspaceMember(workspace_id=workspace.id, user_id=owner.id, role="owner")])
        await db.commit()
    app = FastAPI()
    app.include_router(documents.router, prefix="/api/v1")
    selected = {"user": owner}

    async def override_db():
        async with maker() as db:
            yield db

    async def override_user():
        return selected["user"]

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://local") as client:
        yield client, selected, {"owner": owner, "outsider": outsider}
    await engine.dispose()


@pytest.mark.asyncio
async def test_document_file_route_requires_workspace_access(document_file_client):
    client, selected, users = document_file_client
    allowed = await client.get("/api/v1/documents/invoice/file")
    selected["user"] = users["outsider"]
    denied = await client.get("/api/v1/documents/invoice/file")
    assert allowed.status_code == 200
    assert allowed.text == "Invoice 4471 covers consulting."
    assert denied.status_code == 403

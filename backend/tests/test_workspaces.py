import os
import sys

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.api.routes import chat, documents, workspaces
from app.api.routes.auth import get_current_user
from app.models.database import Base, User, Workspace, WorkspaceMember, get_db


@pytest_asyncio.fixture
async def workspace_client(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'workspaces.db'}")
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    owner = User(id="owner", email="owner@example.com", name="Owner")
    editor = User(id="editor", email="editor@example.com", name="Editor")
    viewer = User(id="viewer", email="viewer@example.com", name="Viewer")
    outsider = User(id="outsider", email="outsider@example.com", name="Outsider")
    workspace = Workspace(id="team", name="Team", owner_id=owner.id)
    async with maker() as db:
        db.add_all([owner, editor, viewer, outsider, workspace,
                    WorkspaceMember(workspace_id="team", user_id="owner", role="owner"),
                    WorkspaceMember(workspace_id="team", user_id="editor", role="editor"),
                    WorkspaceMember(workspace_id="team", user_id="viewer", role="viewer")])
        await db.commit()
    app = FastAPI()
    app.include_router(workspaces.router, prefix="/api/v1")
    app.include_router(documents.router, prefix="/api/v1")
    app.include_router(chat.router, prefix="/api/v1")
    app.state.max_upload_bytes = 1024 * 1024
    selected = {"user": owner}
    async def override_db():
        async with maker() as db:
            yield db
    async def override_user(): return selected["user"]
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user

    async def skip_background_ingestion(document_id: str):
        return "test"

    monkeypatch.setattr(documents, "enqueue_ingestion", skip_background_ingestion)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://local") as client:
        yield client, selected, {"owner": owner, "editor": editor, "viewer": viewer, "outsider": outsider}
    await engine.dispose()


@pytest.mark.asyncio
async def test_owner_can_create_invite_remove_and_delete_workspace(workspace_client):
    client, selected, users = workspace_client
    created = await client.post("/api/v1/workspaces", json={"name": "Owner workspace"})
    assert created.status_code == 201
    workspace_id = created.json()["id"]
    assert created.json()["owner_id"] == users["owner"].id
    assert created.json()["role"] == "owner"

    invited = await client.post(f"/api/v1/workspaces/{workspace_id}/members", json={"email": users["outsider"].email, "role": "viewer"})
    assert invited.status_code == 201
    removed = await client.delete(f"/api/v1/workspaces/{workspace_id}/members/outsider")
    assert removed.status_code == 204
    deleted = await client.delete(f"/api/v1/workspaces/{workspace_id}")
    assert deleted.status_code == 204


@pytest.mark.asyncio
async def test_workspace_owner_cannot_be_removed(workspace_client):
    client, selected, users = workspace_client
    response = await client.delete("/api/v1/workspaces/team/members/owner")
    assert response.status_code == 400
    assert response.json()["detail"] == "The workspace owner cannot be removed"


@pytest.mark.asyncio
async def test_editor_can_upload_but_cannot_manage_members(workspace_client):
    client, selected, users = workspace_client
    selected["user"] = users["editor"]
    upload = await client.post("/api/v1/documents/upload", data={"workspace_id": "team"}, files={"file": ("notes.txt", b"hello", "text/plain")})
    assert upload.status_code == 201
    assert (await client.post("/api/v1/workspaces/team/members", json={"email": users["outsider"].email, "role": "viewer"})).status_code == 403
    assert (await client.delete("/api/v1/workspaces/team/members/viewer")).status_code == 403


@pytest.mark.asyncio
async def test_viewer_can_read_chat_but_cannot_upload(workspace_client):
    client, selected, users = workspace_client
    selected["user"] = users["viewer"]
    assert (await client.get("/api/v1/documents", params={"workspace_id": "team"})).status_code == 200
    assert (await client.get("/api/v1/chat/sessions", params={"workspace_id": "team"})).status_code == 200
    denied = await client.post("/api/v1/documents/upload", data={"workspace_id": "team"}, files={"file": ("notes.txt", b"hello", "text/plain")})
    assert denied.status_code == 403


@pytest.mark.asyncio
async def test_non_member_is_blocked_from_workspace_routes(workspace_client):
    client, selected, users = workspace_client
    selected["user"] = users["outsider"]
    assert (await client.get("/api/v1/workspaces/team/members")).status_code == 403
    assert (await client.get("/api/v1/documents", params={"workspace_id": "team"})).status_code == 403
    assert (await client.get("/api/v1/chat/sessions", params={"workspace_id": "team"})).status_code == 403

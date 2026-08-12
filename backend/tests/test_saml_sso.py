"""SAML route tests use a deterministic assertion adapter, not a live IdP.

The base64 fixture represents the transport field supplied by an IdP. Crypto
and XML-signature validation are delegated to python3-saml in production; the
adapter lets these tests focus on our user/workspace/JWT integration.
"""
import os
import sys
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import pytest_asyncio
from jose import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.api.routes import auth
from app.config import settings
from app.models.database import Base, User, Workspace, WorkspaceMember, get_db

VALID_SAML_RESPONSE = "PHNhbWxwOlJlc3BvbnNlIElEPSJ0ZXN0LWFzc2VydGlvbiI+PC9zYW1scDpSZXNwb25zZT4="


class FixtureSamlAuth:
    def __init__(self, valid: bool):
        self.valid = valid

    def login(self):
        return "https://idp.example.test/sso"

    def process_response(self):
        return None

    def get_errors(self):
        return [] if self.valid else ["invalid_response"]

    def is_authenticated(self):
        return self.valid

    def get_nameid(self):
        return "new.employee@example.test"

    def get_attributes(self):
        return {"email": ["new.employee@example.test"], "displayName": ["New Employee"]}


@pytest_asyncio.fixture
async def saml_client(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'saml.db'}")
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    workspace = Workspace(
        id="enterprise", name="Enterprise", owner_id="owner",
        saml_idp_metadata="<EntityDescriptor/>",
        saml_sp_entity_id="https://app.example.test/saml/entity",
        saml_acs_url="http://local/api/v1/auth/saml/enterprise/acs",
        saml_default_role="viewer",
    )
    async with maker() as db:
        db.add(workspace)
        await db.commit()

    async def override_db():
        async with maker() as db:
            yield db

    async def fake_build_saml_auth(request, workspace, form=None):
        return FixtureSamlAuth((form or {}).get("SAMLResponse") == VALID_SAML_RESPONSE)

    monkeypatch.setattr(auth, "build_saml_auth", fake_build_saml_auth)
    app = __import__("fastapi").FastAPI()
    app.include_router(auth.router, prefix="/api/v1")
    app.dependency_overrides[get_db] = override_db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://local", follow_redirects=False) as client:
        yield client, maker
    await engine.dispose()


@pytest.mark.asyncio
async def test_valid_saml_assertion_jit_provisions_member_and_issues_exchange_jwt(saml_client):
    client, maker = saml_client
    response = await client.post("/api/v1/auth/saml/enterprise/acs", data={"SAMLResponse": VALID_SAML_RESPONSE})
    assert response.status_code == 302
    code = parse_qs(urlparse(response.headers["location"]).query)["code"][0]
    token_response = await client.post("/api/v1/auth/exchange", json={"code": code})
    assert token_response.status_code == 200
    payload = jwt.decode(token_response.json()["access_token"], settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    assert payload["email"] == "new.employee@example.test"
    async with maker() as db:
        user = (await db.execute(select(User).where(User.email == "new.employee@example.test"))).scalar_one()
        membership = (await db.execute(select(WorkspaceMember).where(WorkspaceMember.workspace_id == "enterprise", WorkspaceMember.user_id == user.id))).scalar_one()
    assert membership.role == "viewer"


@pytest.mark.asyncio
async def test_invalid_or_tampered_saml_assertion_is_rejected(saml_client):
    client, maker = saml_client
    response = await client.post("/api/v1/auth/saml/enterprise/acs", data={"SAMLResponse": "tampered"})
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid SAML response"
    async with maker() as db:
        assert (await db.execute(select(User).where(User.email == "new.employee@example.test"))).scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_unconfigured_workspace_returns_clear_saml_error(saml_client):
    client, _ = saml_client
    response = await client.get("/api/v1/auth/saml/not-configured/login")
    assert response.status_code == 503
    assert response.json()["detail"] == "SAML sign-in is not configured for this workspace"

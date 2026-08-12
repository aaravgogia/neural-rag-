import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from fastapi.security import APIKeyHeader, OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.database import APIKey, AuthCode, User, Workspace, WorkspaceMember, get_db
from app.models.schemas import AuthCodeExchange, TokenResponse, UserResponse

router = APIRouter(prefix="/auth", tags=["Authentication"])
logger = logging.getLogger(__name__)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token", auto_error=False)
api_key_scheme = APIKeyHeader(name="X-API-Key", auto_error=False)

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
OAUTH_STATE_COOKIE = "neuralrag_oauth_state"


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    payload = data.copy()
    payload.update({"exp": datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))})
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


async def _create_auth_code(db: AsyncSession, user: User) -> str:
    """Shared provider hand-off: all interactive auth becomes /exchange JWTs."""
    raw_auth_code = secrets.token_urlsafe(32)
    db.add(AuthCode(
        user_id=user.id,
        code_hash=_hash(raw_auth_code),
        expires_at=datetime.utcnow() + timedelta(seconds=settings.AUTH_CODE_TTL_SECONDS),
    ))
    await db.commit()
    return raw_auth_code


def _workspace_has_saml(workspace: Workspace) -> bool:
    return bool(workspace.saml_idp_metadata and workspace.saml_sp_entity_id and workspace.saml_acs_url)


def _saml_request_data(request: Request, form: dict | None = None) -> dict:
    return {
        "https": "on" if request.url.scheme == "https" else "off",
        "http_host": request.headers.get("host", "localhost"),
        "server_port": str(request.url.port or (443 if request.url.scheme == "https" else 80)),
        "script_name": request.url.path,
        "get_data": dict(request.query_params),
        "post_data": form or {},
    }


async def build_saml_auth(request: Request, workspace: Workspace, form: dict | None = None):
    """Build OneLogin's validator from this workspace's IdP metadata."""
    try:
        from onelogin.saml2.auth import OneLogin_Saml2_Auth
        from onelogin.saml2.idp_metadata_parser import OneLogin_Saml2_IdPMetadataParser
    except ImportError as error:
        raise HTTPException(503, "SAML sign-in is not installed on this server") from error

    metadata = workspace.saml_idp_metadata.strip()
    if metadata.startswith(("https://", "http://")):
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                response = await client.get(metadata)
                response.raise_for_status()
                metadata = response.text
        except httpx.HTTPError as error:
            logger.warning("Could not load SAML metadata for workspace %s: %s", workspace.id, error)
            raise HTTPException(503, "Workspace SAML identity provider metadata is unavailable") from error
    try:
        idp = OneLogin_Saml2_IdPMetadataParser.parse(metadata)
    except Exception as error:
        logger.warning("Invalid SAML metadata for workspace %s", workspace.id)
        raise HTTPException(503, "Workspace SAML configuration is invalid") from error
    configuration = {
        "strict": True,
        "debug": settings.DEBUG,
        "sp": {
            "entityId": workspace.saml_sp_entity_id,
            "assertionConsumerService": {"url": workspace.saml_acs_url, "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"},
        },
        **idp,
    }
    return OneLogin_Saml2_Auth(_saml_request_data(request, form), old_settings=configuration)


async def authenticate_api_key(raw_key: str, db: AsyncSession) -> User | None:
    key = (await db.execute(select(APIKey).where(APIKey.key_hash == _hash(raw_key), APIKey.revoked_at.is_(None)))).scalar_one_or_none()
    if not key:
        return None
    user = (await db.execute(select(User).where(User.id == key.user_id))).scalar_one_or_none()
    if not user or not user.is_active:
        return None
    key.last_used_at = datetime.utcnow()
    await db.commit()
    return user


async def get_current_user(token: str = Depends(oauth2_scheme), api_key: str | None = Depends(api_key_scheme), db: AsyncSession = Depends(get_db)) -> User:
    # X-API-Key is intended for programmatic clients; Bearer nrg_* also works
    # with tools that cannot send a custom header.
    raw_api_key = api_key or (token if token and token.startswith("nrg_") else None)
    if raw_api_key:
        user = await authenticate_api_key(raw_api_key, db)
        if user:
            return user
        raise HTTPException(401, "Invalid API key")
    if not token:
        raise HTTPException(401, "Invalid credentials")
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(401, "Invalid credentials")
    except JWTError as error:
        raise HTTPException(401, "Invalid credentials") from error

    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(401, "Invalid credentials")
    return user


@router.get("/google/login")
async def google_login():
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        raise HTTPException(503, "Google sign-in is not configured on this server")

    state = secrets.token_urlsafe(32)
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": settings.GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "offline",
        "prompt": "consent",
    }
    response = RedirectResponse(f"{GOOGLE_AUTH_URL}?{urlencode(params)}", status_code=302)
    response.set_cookie(
        OAUTH_STATE_COOKIE,
        state,
        max_age=settings.OAUTH_STATE_TTL_SECONDS,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/api/v1/auth/google",
    )
    return response


@router.get("/google/callback")
async def google_callback(code: str, state: str, request: Request, db: AsyncSession = Depends(get_db)):
    expected_state = request.cookies.get(OAUTH_STATE_COOKIE)
    if not expected_state or not secrets.compare_digest(expected_state, state):
        raise HTTPException(400, "Invalid OAuth state")

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            token_response = await client.post(GOOGLE_TOKEN_URL, data={
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": settings.GOOGLE_REDIRECT_URI,
            })
            token_response.raise_for_status()
            provider_token = token_response.json().get("access_token")
            if not provider_token:
                raise HTTPException(502, "Google did not return an access token")
            userinfo_response = await client.get(GOOGLE_USERINFO_URL, headers={"Authorization": f"Bearer {provider_token}"})
            userinfo_response.raise_for_status()
            user_info = userinfo_response.json()
    except httpx.HTTPError as error:
        logger.warning("Google OAuth request failed: %s", error)
        raise HTTPException(502, "Could not complete Google sign-in") from error

    google_id, email = user_info.get("id"), user_info.get("email")
    if not google_id or not email or user_info.get("verified_email") is False:
        raise HTTPException(403, "Google account email could not be verified")

    user = (await db.execute(select(User).where(User.google_id == google_id))).scalar_one_or_none()
    if not user:
        user = User(email=email, name=user_info.get("name", ""), picture=user_info.get("picture"), google_id=google_id)
        db.add(user)
    user.last_login = datetime.utcnow()
    await db.flush()

    raw_auth_code = await _create_auth_code(db, user)

    response = RedirectResponse(f"{settings.FRONTEND_URL.rstrip('/')}/auth/callback?code={raw_auth_code}", status_code=302)
    response.delete_cookie(OAUTH_STATE_COOKIE, path="/api/v1/auth/google")
    return response


@router.get("/saml/{workspace_id}/login")
async def saml_login(workspace_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    workspace = (await db.execute(select(Workspace).where(Workspace.id == workspace_id))).scalar_one_or_none()
    if not workspace or not _workspace_has_saml(workspace):
        raise HTTPException(503, "SAML sign-in is not configured for this workspace")
    auth = await build_saml_auth(request, workspace)
    return RedirectResponse(auth.login(), status_code=302)


@router.post("/saml/{workspace_id}/acs")
async def saml_acs(workspace_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    workspace = (await db.execute(select(Workspace).where(Workspace.id == workspace_id))).scalar_one_or_none()
    if not workspace or not _workspace_has_saml(workspace):
        raise HTTPException(503, "SAML sign-in is not configured for this workspace")
    form = dict(await request.form())
    auth = await build_saml_auth(request, workspace, form)
    try:
        auth.process_response()
        if auth.get_errors() or not auth.is_authenticated():
            raise ValueError(", ".join(auth.get_errors()) or "assertion was not authenticated")
        attributes = auth.get_attributes() or {}
        email = (attributes.get("email", attributes.get("mail", [auth.get_nameid()]))[0] or "").strip().lower()
        if "@" not in email:
            raise ValueError("assertion did not contain a valid email address")
    except Exception as error:
        logger.warning("Rejected SAML assertion for workspace %s: %s", workspace_id, error)
        raise HTTPException(401, "Invalid SAML response") from error

    name_values = attributes.get("displayName", attributes.get("name", [email.split("@", 1)[0]]))
    user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if not user:
        user = User(email=email, name=str(name_values[0]))
        db.add(user)
        await db.flush()
    user.last_login = datetime.utcnow()
    member = (await db.execute(select(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace.id, WorkspaceMember.user_id == user.id))).scalar_one_or_none()
    if not member:
        role = workspace.saml_default_role if workspace.saml_default_role in {"viewer", "editor"} else "viewer"
        db.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role=role))
    raw_auth_code = await _create_auth_code(db, user)
    return RedirectResponse(f"{settings.FRONTEND_URL.rstrip('/')}/auth/callback?code={raw_auth_code}", status_code=302)


@router.post("/exchange", response_model=TokenResponse)
async def exchange_auth_code(body: AuthCodeExchange, db: AsyncSession = Depends(get_db)):
    auth_code = (await db.execute(select(AuthCode).where(AuthCode.code_hash == _hash(body.code)))).scalar_one_or_none()
    if not auth_code or auth_code.used_at or auth_code.expires_at < datetime.utcnow():
        raise HTTPException(401, "Invalid or expired authorization code")
    user = (await db.execute(select(User).where(User.id == auth_code.user_id))).scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(401, "Invalid credentials")
    auth_code.used_at = datetime.utcnow()
    await db.commit()
    return TokenResponse(access_token=create_access_token({"sub": user.id, "email": user.email}), user=user)


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(current_user: User = Depends(get_current_user)):
    return current_user

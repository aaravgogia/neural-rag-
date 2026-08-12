"""Programmatic credentials, separate from the browser's OAuth/JWT session."""
import hashlib
import secrets
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.auth import get_current_user
from app.models.database import APIKey, User, get_db
from app.models.schemas import APIKeyCreate, APIKeyResponse

router = APIRouter(prefix="/api-keys", tags=["API keys"])


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _response(api_key: APIKey, plaintext: str | None = None) -> APIKeyResponse:
    return APIKeyResponse(id=api_key.id, name=api_key.name, prefix=api_key.key_prefix,
                          created_at=api_key.created_at, last_used_at=api_key.last_used_at, key=plaintext)


@router.get("", response_model=list[APIKeyResponse])
async def list_api_keys(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    keys = (await db.execute(select(APIKey).where(APIKey.user_id == current_user.id, APIKey.revoked_at.is_(None)).order_by(APIKey.created_at.desc()))).scalars().all()
    return [_response(key) for key in keys]


@router.post("", response_model=APIKeyResponse, status_code=status.HTTP_201_CREATED)
async def create_api_key(body: APIKeyCreate, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    plaintext = f"nrg_{secrets.token_urlsafe(32)}"
    api_key = APIKey(user_id=current_user.id, name=body.name.strip(), key_prefix=plaintext[:12], key_hash=_digest(plaintext))
    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)
    return _response(api_key, plaintext)


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(key_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    api_key = (await db.execute(select(APIKey).where(APIKey.id == key_id, APIKey.user_id == current_user.id, APIKey.revoked_at.is_(None)))).scalar_one_or_none()
    if not api_key:
        raise HTTPException(404, "API key not found")
    api_key.revoked_at = datetime.utcnow()
    await db.commit()

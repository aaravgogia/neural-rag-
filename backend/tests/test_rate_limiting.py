import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.routes.api_keys import create_api_key, revoke_api_key
from app.api.routes.auth import get_current_user
from app.core.security import RateLimitExceeded, ResilientRateLimiter
from app.models.database import APIKey, Base, User
from app.models.schemas import APIKeyCreate


@pytest.mark.asyncio
async def test_in_memory_rate_limit_enforces_and_resets_after_window():
    now = [100.0]
    limiter = ResilientRateLimiter(window_seconds=60, clock=lambda: now[0])
    await limiter.check("user-1", limit=2)
    await limiter.check("user-1", limit=2)
    with pytest.raises(RateLimitExceeded) as error:
        await limiter.check("user-1", limit=2)
    assert error.value.status_code == 429
    assert error.value.headers["Retry-After"] == "60"

    now[0] += 60
    await limiter.check("user-1", limit=2)


@pytest.mark.asyncio
async def test_api_key_authentication_is_independent_of_jwt_session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'keys.db'}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    try:
        async with sessions() as db:
            user = User(email="api-key@example.test", name="API key user", google_id="api-key-user")
            db.add(user)
            await db.commit()
            await db.refresh(user)

            created = await create_api_key(APIKeyCreate(name="CI client"), current_user=user, db=db)
            assert created.key and created.key.startswith("nrg_")
            stored = (await db.execute(select(APIKey).where(APIKey.id == created.id))).scalar_one()
            assert stored.key_hash != created.key
            assert created.key not in stored.key_hash

            authenticated = await get_current_user(token=None, api_key=created.key, db=db)
            assert authenticated.id == user.id

            await revoke_api_key(created.id, current_user=user, db=db)
            with pytest.raises(Exception) as error:
                await get_current_user(token=None, api_key=created.key, db=db)
            assert getattr(error.value, "status_code", None) == 401
    finally:
        await engine.dispose()

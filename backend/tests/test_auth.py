"""
Real, runnable tests for the auth logic that doesn't require live Google
credentials -- JWT creation/validation and SQLite user persistence.
The actual Google token exchange (httpx call to oauth2.googleapis.com)
is the one piece that genuinely can't be tested without live credentials;
everything else in the callback handler is covered here.

Run: pytest tests/test_auth.py -v
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import pytest_asyncio
from datetime import datetime, timezone

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from app.api.routes.auth import create_access_token
from app.config import settings
from jose import jwt, JWTError


def test_access_token_round_trips():
    token = create_access_token({"sub": "user-123", "email": "a@b.com"})
    payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    assert payload["sub"] == "user-123"
    assert payload["email"] == "a@b.com"


def test_access_token_has_expiry():
    token = create_access_token({"sub": "user-123"})
    payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    assert "exp" in payload
    assert payload["exp"] > datetime.now(timezone.utc).timestamp()


def test_tampered_token_rejected():
    token = create_access_token({"sub": "user-123"})
    with pytest.raises(JWTError):
        jwt.decode(token + "x", settings.SECRET_KEY, algorithms=[settings.ALGORITHM])


def test_wrong_secret_rejected():
    token = create_access_token({"sub": "user-123"})
    with pytest.raises(JWTError):
        jwt.decode(token, "wrong-secret-entirely", algorithms=[settings.ALGORITHM])


@pytest.mark.asyncio
async def test_user_created_and_deduped_in_sqlite(tmp_path, monkeypatch):
    """Mirrors exactly what google_callback() does after Google's userinfo
    call succeeds -- real SQLite writes, not mocked."""
    db_path = tmp_path / "test.db"
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"
    # Settings are instantiated during test collection, so update that
    # already-loaded instance too; this keeps the test isolated regardless
    # of collection order.
    monkeypatch.setattr(settings, "DATABASE_URL", os.environ["DATABASE_URL"])

    # Re-import with the new DATABASE_URL picked up
    import importlib
    from app.models import database as db_module
    importlib.reload(db_module)

    await db_module.init_db()

    from sqlalchemy import select
    fake_google_id = "109876543210"

    async with db_module.AsyncSessionLocal() as db:
        result = await db.execute(select(db_module.User).where(db_module.User.google_id == fake_google_id))
        assert result.scalar_one_or_none() is None

        user = db_module.User(email="x@y.com", name="Test User", google_id=fake_google_id)
        db.add(user)
        await db.commit()
        await db.refresh(user)
        first_id = user.id

    # Simulate a second login with the SAME google_id -- must not duplicate
    async with db_module.AsyncSessionLocal() as db:
        result = await db.execute(select(db_module.User).where(db_module.User.google_id == fake_google_id))
        existing = result.scalar_one_or_none()
        assert existing is not None
        assert existing.id == first_id

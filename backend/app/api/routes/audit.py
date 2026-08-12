"""Admin-only audit access for enterprise review workflows."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.auth import get_current_user
from app.models.database import AuditLog, User, get_db

router = APIRouter(prefix="/audit", tags=["Audit"])


async def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if not current_user.is_admin:
        raise HTTPException(403, "Administrator access required")
    return current_user


@router.get("")
async def list_audit_logs(limit: int = Query(50, ge=1, le=200), db: AsyncSession = Depends(get_db), current_user: User = Depends(require_admin)):
    rows = (await db.execute(select(AuditLog).order_by(AuditLog.timestamp.desc()).limit(limit))).scalars().all()
    return [{"id": row.id, "user_id": row.user_id, "query_text": row.query_text, "document_ids_used": row.document_ids_used or [], "timestamp": row.timestamp.isoformat()} for row in rows]

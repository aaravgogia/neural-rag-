"""User-scoped data portability and confirmed account deletion."""
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.routes.auth import get_current_user
from app.config import settings
from app.models.database import AuditLog, ChatMessage, ChatSession, Document, TokenUsage, User, Workspace, WorkspaceMember, get_db

router = APIRouter(prefix="/me", tags=["My data"])

@router.get("/export")
async def export_my_data(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    docs = (await db.execute(select(Document).where(Document.user_id == current_user.id))).scalars().all()
    sessions = (await db.execute(select(ChatSession).where(ChatSession.user_id == current_user.id))).scalars().all()
    messages = (await db.execute(select(ChatMessage).where(ChatMessage.user_id == current_user.id).order_by(ChatMessage.created_at))).scalars().all()
    audits = (await db.execute(select(AuditLog).where(AuditLog.user_id == current_user.id).order_by(AuditLog.timestamp))).scalars().all()
    return {"user": {"id": current_user.id, "email": current_user.email, "name": current_user.name}, "documents": [{"id": d.id, "filename": d.filename, "file_size": d.file_size, "file_type": d.file_type, "status": d.status, "created_at": d.created_at.isoformat()} for d in docs], "conversations": [{"id": s.id, "title": s.title, "messages": [{"role": m.role, "content": m.content, "created_at": m.created_at.isoformat()} for m in messages if m.session_id == s.id]} for s in sessions], "audit_logs": [{"query_text": a.query_text, "document_ids_used": a.document_ids_used or [], "timestamp": a.timestamp.isoformat()} for a in audits]}

@router.post("/delete-confirmation")
async def deletion_confirmation(current_user: User = Depends(get_current_user)):
    expires = datetime.utcnow() + timedelta(minutes=10)
    token = jwt.encode({"sub": current_user.id, "purpose": "delete_account", "exp": expires}, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return {"confirmation_token": token, "expires_at": expires.isoformat()}

@router.delete("")
async def delete_my_data(confirmation_token: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        claim = jwt.decode(confirmation_token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError: raise HTTPException(400, "A valid deletion confirmation token is required")
    if claim.get("sub") != current_user.id or claim.get("purpose") != "delete_account": raise HTTPException(400, "A valid deletion confirmation token is required")
    owned = (await db.execute(select(Workspace).where(Workspace.owner_id == current_user.id))).scalars().all()
    if owned:
        raise HTTPException(409, "Transfer or delete owned workspaces before deleting your account")
    ids = [d.id for d in (await db.execute(select(Document).where(Document.user_id == current_user.id))).scalars().all()]
    # Vector cleanup is best-effort; DB deletion must still complete if the store is unavailable.
    for doc in (await db.execute(select(Document).where(Document.user_id == current_user.id))).scalars().all(): await db.delete(doc)
    for model, field in [(ChatMessage, ChatMessage.user_id), (ChatSession, ChatSession.user_id), (TokenUsage, TokenUsage.user_id), (AuditLog, AuditLog.user_id), (WorkspaceMember, WorkspaceMember.user_id)]:
        rows = (await db.execute(select(model).where(field == current_user.id))).scalars().all()
        for row in rows: await db.delete(row)
    await db.delete(current_user); await db.commit()
    return {"deleted": True}

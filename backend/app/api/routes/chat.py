import logging
import time
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.auth import get_current_user
from app.config import settings
from app.core.security import ResilientRateLimiter, validate_namespace
from app.core.workspaces import require_workspace_role
from app.core.quotas import enforce_workspace_quota
from app.models.database import AuditLog, ChatMessage, ChatSession, User, Workspace, get_db
from app.models.schemas import ChatRequest, ChatResponse, ChatSessionCreate, ChatSessionResponse, MessageResponse

router = APIRouter(prefix="/chat", tags=["Chat"])
logger = logging.getLogger(__name__)


async def enforce_chat_rate_limit(request: Request, current_user: User = Depends(get_current_user)) -> User:
    """Charge only expensive generation requests, keyed by stable user id."""
    limiter: ResilientRateLimiter = request.app.state.rate_limiter
    await limiter.check(f"chat:user:{current_user.id}", settings.AUTHENTICATED_CHAT_REQUESTS_PER_MINUTE)
    return current_user


async def owned_session(session_id: str, user_id: str, db: AsyncSession) -> ChatSession:
    session = (await db.execute(select(ChatSession).where(ChatSession.id == session_id))).scalar_one_or_none()
    if not session:
        raise HTTPException(404, "Chat session not found")
    await require_workspace_role(db, session.workspace_id, user_id)
    return session

async def enforce_session_quota(db: AsyncSession, session: ChatSession) -> dict:
    workspace = (await db.execute(select(Workspace).where(Workspace.id == session.workspace_id))).scalar_one_or_none()
    if not workspace:
        raise HTTPException(404, "Workspace not found")
    return await enforce_workspace_quota(db, workspace)


@router.get("/sessions", response_model=list[ChatSessionResponse])
async def list_sessions(workspace_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require_workspace_role(db, workspace_id, current_user.id)
    result = await db.execute(select(ChatSession).where(ChatSession.workspace_id == workspace_id).order_by(ChatSession.updated_at.desc()))
    return result.scalars().all()


@router.post("/sessions", response_model=ChatSessionResponse, status_code=201)
async def create_session(body: ChatSessionCreate, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require_workspace_role(db, body.workspace_id, current_user.id)
    session = ChatSession(user_id=current_user.id, workspace_id=body.workspace_id, title=(body.title or "New Chat").strip()[:120] or "New Chat", namespace=validate_namespace(body.namespace))
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


@router.get("/sessions/{session_id}/messages", response_model=list[MessageResponse])
async def list_messages(session_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await owned_session(session_id, current_user.id, db)
    result = await db.execute(select(ChatMessage).where(ChatMessage.session_id == session_id, ChatMessage.user_id == current_user.id).order_by(ChatMessage.created_at))
    return result.scalars().all()


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(session_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    session = await owned_session(session_id, current_user.id, db)
    await db.execute(ChatMessage.__table__.delete().where(ChatMessage.session_id == session.id, ChatMessage.user_id == current_user.id))
    await db.delete(session)
    await db.commit()


@router.post("/query", response_model=ChatResponse)
async def chat_query(request: Request, body: ChatRequest, current_user: User = Depends(enforce_chat_rate_limit), db: AsyncSession = Depends(get_db)):
    session = await owned_session(body.session_id, current_user.id, db)
    await enforce_session_quota(db, session)
    start_time = time.perf_counter()
    try:
        # Namespace is selected when the server-owned session is created; the
        # client value is deliberately ignored to prevent cross-tenant reads.
        if body.use_agent:
            result = await request.app.state.graph_agent.run(body.question, session.id, user_id=current_user.id, workspace_id=session.workspace_id, namespace=session.namespace)
        else:
            result = await request.app.state.rag_pipeline.query(body.question, user_id=current_user.id, workspace_id=session.workspace_id, namespace=session.namespace)
        processing_time = time.perf_counter() - start_time
        user_message = ChatMessage(session_id=session.id, user_id=current_user.id, role="human", content=body.question)
        ai_message = ChatMessage(id=str(uuid.uuid4()), session_id=session.id, user_id=current_user.id, role="ai", content=result["answer"], sources=result.get("sources", []), processing_time=processing_time)
        document_ids = list(dict.fromkeys(source["document_id"] for source in result.get("sources", []) if source.get("document_id")))
        db.add_all([user_message, ai_message, AuditLog(user_id=current_user.id, query_text=body.question, document_ids_used=document_ids)])
        session.message_count += 2
        session.updated_at = datetime.utcnow()
        current_user.total_queries += 1
        await db.commit()
        return ChatResponse(answer=result["answer"], sources=result.get("sources", []), session_id=session.id, question=body.question, processing_time=processing_time, message_id=ai_message.id)
    except HTTPException:
        raise
    except Exception as error:
        logger.exception("Chat query failed")
        raise HTTPException(500, "Could not process the question") from error


@router.post("/stream")
async def stream_chat(request: Request, body: ChatRequest, current_user: User = Depends(enforce_chat_rate_limit), db: AsyncSession = Depends(get_db)):
    session = await owned_session(body.session_id, current_user.id, db)
    await enforce_session_quota(db, session)
    # The streaming transport does not currently return source metadata; the
    # query is still audited, with an intentionally empty document-id list.
    db.add(AuditLog(user_id=current_user.id, query_text=body.question, document_ids_used=[]))
    await db.commit()

    async def generate():
        async for chunk in request.app.state.rag_pipeline.stream_query(body.question, user_id=current_user.id, workspace_id=session.workspace_id, namespace=session.namespace):
            yield f"data: {chunk}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

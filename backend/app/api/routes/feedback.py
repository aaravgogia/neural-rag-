"""Answer feedback and the privileged negative-answer review queue."""
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.auth import get_current_user
from app.core.workspaces import require_workspace_role
from app.models.database import ChatMessage, ChatSession, EvalMetric, Feedback, User, WorkspaceMember, get_db
from app.models.schemas import FeedbackCreate, FeedbackResponse

router = APIRouter(prefix="/feedback", tags=["Feedback"])


async def _session_for_member(db: AsyncSession, session_id: str, user_id: str) -> ChatSession:
    session = (await db.execute(select(ChatSession).where(ChatSession.id == session_id))).scalar_one_or_none()
    if not session:
        raise HTTPException(404, "Chat session not found")
    await require_workspace_role(db, session.workspace_id, user_id)
    return session


async def _question_for_answer(db: AsyncSession, message: ChatMessage) -> str:
    """Return the user turn immediately preceding the reviewed answer."""
    question = (await db.execute(select(ChatMessage.content).where(
        ChatMessage.session_id == message.session_id,
        ChatMessage.role == "human",
        ChatMessage.created_at <= message.created_at,
    ).order_by(ChatMessage.created_at.desc()).limit(1))).scalar_one_or_none()
    return question or ""


@router.post("", response_model=FeedbackResponse, status_code=status.HTTP_201_CREATED)
async def submit_feedback(body: FeedbackCreate, response: Response, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _session_for_member(db, body.session_id, current_user.id)
    message = (await db.execute(select(ChatMessage).where(
        ChatMessage.id == body.message_id, ChatMessage.session_id == body.session_id, ChatMessage.role == "ai"
    ))).scalar_one_or_none()
    if not message:
        raise HTTPException(404, "Assistant message not found in this session")
    evaluation = (await db.execute(select(EvalMetric).where(EvalMetric.session_id == body.session_id)
        .order_by(EvalMetric.timestamp.desc()).limit(1))).scalar_one_or_none()
    feedback = (await db.execute(select(Feedback).where(
        Feedback.message_id == body.message_id, Feedback.user_id == current_user.id
    ))).scalar_one_or_none()
    if feedback:
        feedback.rating, feedback.comment = body.rating, body.comment
        feedback.eval_metric_id = evaluation.id if evaluation else None
        await db.commit()
        await db.refresh(feedback)
        response.status_code = status.HTTP_200_OK
        return feedback
    feedback = Feedback(message_id=body.message_id, session_id=body.session_id, user_id=current_user.id,
                        rating=body.rating, comment=body.comment, eval_metric_id=evaluation.id if evaluation else None)
    db.add(feedback)
    await db.commit()
    await db.refresh(feedback)
    return feedback


@router.get("/negative")
async def negative_feedback_queue(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    owner_workspaces = select(WorkspaceMember.workspace_id).where(
        WorkspaceMember.user_id == current_user.id, WorkspaceMember.role == "owner"
    )
    if not current_user.is_admin:
        has_workspace = (await db.execute(owner_workspaces.limit(1))).scalar_one_or_none()
        if has_workspace is None:
            raise HTTPException(403, "Administrator or workspace owner access required")
    query = (select(Feedback, ChatMessage, ChatSession, EvalMetric)
             .join(ChatMessage, ChatMessage.id == Feedback.message_id)
             .join(ChatSession, ChatSession.id == Feedback.session_id)
             .outerjoin(EvalMetric, EvalMetric.id == Feedback.eval_metric_id)
             .where(Feedback.rating == "down"))
    if not current_user.is_admin:
        query = query.where(ChatSession.workspace_id.in_(owner_workspaces))
    rows = (await db.execute(query.order_by(Feedback.created_at.desc()))).all()
    queue = []
    for feedback, message, session, metric in rows:
        queue.append({
            "feedback_id": feedback.id,
            "message_id": feedback.message_id,
            "session_id": feedback.session_id,
            "query": await _question_for_answer(db, message),
            "answer": message.content,
            "retrieved_chunks": message.sources or [],
            "groundedness": metric.groundedness if metric else None,
            "retrieval_relevance": metric.retrieval_relevance if metric else None,
            "comment": feedback.comment,
            "created_at": feedback.created_at.isoformat(),
        })
    return queue

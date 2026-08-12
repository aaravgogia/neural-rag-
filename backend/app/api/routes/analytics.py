from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from datetime import date, datetime, timedelta, time

from app.models.database import get_db, ChatMessage, ChatSession, Document, Feedback, TokenUsage, Workspace
from app.core.quotas import quota_for_plan, workspace_usage
from app.core.workspaces import require_workspace_role
from app.api.routes.auth import get_current_user
from app.models.database import User

router = APIRouter(prefix="/analytics", tags=["Analytics"])


def summarize_costs(records: list[TokenUsage]) -> dict:
    """Database-neutral daily grouping used by SQLite and Postgres alike."""
    days: dict[str, dict] = {}
    for record in records:
        key = record.created_at.date().isoformat()
        day = days.setdefault(key, {"date": key, "cost_usd": 0.0, "prompt_tokens": 0, "completion_tokens": 0, "requests": 0})
        day["cost_usd"] += float(record.estimated_cost_usd or 0)
        day["prompt_tokens"] += int(record.prompt_tokens or 0)
        day["completion_tokens"] += int(record.completion_tokens or 0)
        day["requests"] += 1
    daily = [{**value, "cost_usd": round(value["cost_usd"], 8)} for _, value in sorted(days.items())]
    return {
        "total_cost_usd": round(sum(item["cost_usd"] for item in daily), 8),
        "total_prompt_tokens": sum(item["prompt_tokens"] for item in daily),
        "total_completion_tokens": sum(item["completion_tokens"] for item in daily),
        "total_requests": sum(item["requests"] for item in daily),
        "daily": daily,
    }

@router.get("/dashboard")
async def get_dashboard_analytics(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    user_id = current_user.id

    total_q = await db.execute(select(func.count(ChatMessage.id)).where(ChatMessage.user_id == user_id, ChatMessage.role == "human"))
    today = datetime.utcnow().replace(hour=0, minute=0, second=0)
    today_q = await db.execute(select(func.count(ChatMessage.id)).where(
        ChatMessage.user_id == user_id, ChatMessage.role == "human", ChatMessage.created_at >= today))
    total_docs = await db.execute(select(func.count(Document.id)).where(Document.user_id == user_id))
    total_sessions = await db.execute(select(func.count(ChatSession.id)).where(ChatSession.user_id == user_id))
    avg_time = await db.execute(select(func.avg(ChatMessage.processing_time)).where(
        ChatMessage.user_id == user_id, ChatMessage.role == "ai"))
    votes = (await db.execute(select(Feedback.rating).where(Feedback.user_id == user_id))).scalars().all()
    satisfaction_rate = round((sum(rating == "up" for rating in votes) / len(votes)) * 100, 1) if votes else 0.0

    daily_activity = []
    for i in range(7):
        day = datetime.utcnow() - timedelta(days=i)
        day_start, day_end = day.replace(hour=0, minute=0, second=0), day.replace(hour=23, minute=59, second=59)
        count = await db.execute(select(func.count(ChatMessage.id)).where(
            ChatMessage.user_id == user_id, ChatMessage.created_at.between(day_start, day_end)))
        daily_activity.append({"date": day.strftime("%Y-%m-%d"), "queries": count.scalar() or 0})

    doc_types = await db.execute(select(Document.file_type, func.count(Document.id)).where(
        Document.user_id == user_id).group_by(Document.file_type))

    return {
        "total_queries": total_q.scalar() or 0,
        "total_documents": total_docs.scalar() or 0,
        "total_sessions": total_sessions.scalar() or 0,
        "queries_today": today_q.scalar() or 0,
        "avg_response_time": round(float(avg_time.scalar() or 0), 2),
        "satisfaction_rate": satisfaction_rate,
        "daily_activity": list(reversed(daily_activity)),
        "document_types": [{"type": row[0], "count": row[1]} for row in doc_types.fetchall()],
        "top_topics": []
    }


@router.get("/costs")
async def get_cost_analytics(
    start_date: date | None = None,
    end_date: date | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = select(TokenUsage).where(TokenUsage.user_id == current_user.id)
    if start_date:
        query = query.where(TokenUsage.created_at >= datetime.combine(start_date, time.min))
    if end_date:
        query = query.where(TokenUsage.created_at <= datetime.combine(end_date, time.max))
    records = (await db.execute(query.order_by(TokenUsage.created_at))).scalars().all()
    return summarize_costs(records)

@router.get("/usage")
async def get_workspace_usage(workspace_id: str, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    await require_workspace_role(db, workspace_id, current_user.id)
    workspace = (await db.execute(select(Workspace).where(Workspace.id == workspace_id))).scalar_one_or_none()
    if not workspace:
        return {"plan": "free", "usage": {"tokens": 0, "requests": 0}, "limit": {"tokens": 0, "requests": 0}}
    usage = await workspace_usage(db, workspace_id)
    quota = quota_for_plan(workspace.plan)
    return {"plan": workspace.plan, "usage": {"tokens": usage["tokens"], "requests": usage["requests"]}, "limit": {"tokens": quota.token_limit, "requests": quota.request_limit}}

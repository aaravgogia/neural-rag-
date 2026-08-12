"""Workspace plan limits enforced before expensive generation starts."""
from dataclasses import dataclass
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.token_usage import summarize_usage
from app.models.database import ChatSession, TokenUsage, Workspace


@dataclass(frozen=True)
class PlanQuota:
    token_limit: int
    request_limit: int


def quota_for_plan(plan: str) -> PlanQuota:
    if plan == "pro":
        return PlanQuota(settings.PRO_MONTHLY_TOKEN_QUOTA, settings.PRO_MONTHLY_REQUEST_QUOTA)
    return PlanQuota(settings.FREE_MONTHLY_TOKEN_QUOTA, settings.FREE_MONTHLY_REQUEST_QUOTA)


def month_start(now: datetime) -> datetime:
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def workspace_usage(db: AsyncSession, workspace_id: str, now: datetime | None = None) -> dict:
    now = now or datetime.utcnow()
    records = (await db.execute(select(TokenUsage).join(ChatSession, ChatSession.id == TokenUsage.session_id).where(
        ChatSession.workspace_id == workspace_id, TokenUsage.created_at >= month_start(now), TokenUsage.created_at <= now
    ))).scalars().all()
    return summarize_usage(records)


async def enforce_workspace_quota(db: AsyncSession, workspace: Workspace, now: datetime | None = None) -> dict:
    usage = await workspace_usage(db, workspace.id, now)
    quota = quota_for_plan(workspace.plan)
    if usage["tokens"] >= quota.token_limit or usage["requests"] >= quota.request_limit:
        raise HTTPException(402, detail={
            "message": "Monthly workspace quota reached. Upgrade to Pro or wait for the next billing month.",
            "plan": workspace.plan,
            "usage": {"tokens": usage["tokens"], "requests": usage["requests"]},
            "limit": {"tokens": quota.token_limit, "requests": quota.request_limit},
        })
    return {"plan": workspace.plan, "usage": usage, "limit": {"tokens": quota.token_limit, "requests": quota.request_limit}}

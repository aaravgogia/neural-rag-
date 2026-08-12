from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.database import WorkspaceMember

ROLE_ORDER = {"viewer": 0, "editor": 1, "owner": 2}

async def require_workspace_role(db: AsyncSession, workspace_id: str, user_id: str, minimum: str = "viewer") -> WorkspaceMember:
    member = (await db.execute(select(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.user_id == user_id))).scalar_one_or_none()
    if not member:
        raise HTTPException(403, "You are not a member of this workspace")
    if ROLE_ORDER.get(member.role, -1) < ROLE_ORDER[minimum]:
        raise HTTPException(403, f"Workspace {minimum} role required")
    return member

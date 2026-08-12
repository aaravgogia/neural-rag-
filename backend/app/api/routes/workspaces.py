from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.routes.auth import get_current_user
from app.core.workspaces import require_workspace_role
from app.models.database import Document, User, Workspace, WorkspaceMember, get_db
from app.models.schemas import WorkspaceCreate, WorkspaceInvite

router = APIRouter(prefix="/workspaces", tags=["Workspaces"])

def serialize(workspace, role):
    return {"id": workspace.id, "name": workspace.name, "owner_id": workspace.owner_id, "role": role, "plan": workspace.plan, "created_at": workspace.created_at}

@router.get("")
async def list_workspaces(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Workspace, WorkspaceMember.role).join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id).where(WorkspaceMember.user_id == current_user.id).order_by(Workspace.created_at))).all()
    return [serialize(workspace, role) for workspace, role in rows]

@router.post("", status_code=status.HTTP_201_CREATED)
async def create_workspace(body: WorkspaceCreate, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    workspace = Workspace(name=body.name.strip(), owner_id=current_user.id)
    db.add(workspace); await db.flush()
    db.add(WorkspaceMember(workspace_id=workspace.id, user_id=current_user.id, role="owner"))
    await db.commit(); await db.refresh(workspace)
    return serialize(workspace, "owner")

@router.get("/{workspace_id}/members")
async def list_members(workspace_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require_workspace_role(db, workspace_id, current_user.id)
    rows = (await db.execute(select(WorkspaceMember, User).join(User, User.id == WorkspaceMember.user_id).where(WorkspaceMember.workspace_id == workspace_id))).all()
    return [{"user_id": member.user_id, "email": user.email, "name": user.name, "role": member.role} for member, user in rows]

@router.post("/{workspace_id}/members", status_code=status.HTTP_201_CREATED)
async def invite_member(workspace_id: str, body: WorkspaceInvite, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require_workspace_role(db, workspace_id, current_user.id, "owner")
    user = (await db.execute(select(User).where(User.email == body.email.lower()))).scalar_one_or_none()
    if not user:
        raise HTTPException(404, "No user found with that email")
    existing = (await db.execute(select(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.user_id == user.id))).scalar_one_or_none()
    if existing:
        raise HTTPException(409, "User is already a workspace member")
    member = WorkspaceMember(workspace_id=workspace_id, user_id=user.id, role=body.role)
    db.add(member); await db.commit()
    return {"user_id": user.id, "email": user.email, "name": user.name, "role": member.role}

@router.delete("/{workspace_id}/members/{member_user_id}", status_code=204)
async def remove_member(workspace_id: str, member_user_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require_workspace_role(db, workspace_id, current_user.id, "owner")
    workspace = (await db.execute(select(Workspace).where(Workspace.id == workspace_id))).scalar_one_or_none()
    if not workspace:
        raise HTTPException(404, "Workspace not found")
    if member_user_id == workspace.owner_id:
        raise HTTPException(400, "The workspace owner cannot be removed")
    member = (await db.execute(select(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.user_id == member_user_id))).scalar_one_or_none()
    if not member:
        raise HTTPException(404, "Workspace member not found")
    await db.delete(member); await db.commit()

@router.delete("/{workspace_id}", status_code=204)
async def delete_workspace(workspace_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require_workspace_role(db, workspace_id, current_user.id, "owner")
    workspace = (await db.execute(select(Workspace).where(Workspace.id == workspace_id))).scalar_one_or_none()
    if not workspace:
        raise HTTPException(404, "Workspace not found")
    await db.execute(WorkspaceMember.__table__.delete().where(WorkspaceMember.workspace_id == workspace_id))
    await db.delete(workspace); await db.commit()

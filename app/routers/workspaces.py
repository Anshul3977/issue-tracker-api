"""Workspaces and membership."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import get_current_user, require_workspace
from app.errors import APIError
from app.models import Membership, User, Workspace
from app.present import member_out, workspace_out
from app.schemas import MemberIn, MemberOut, WorkspaceIn, WorkspaceOut, WorkspaceUpdate

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


@router.post("", response_model=WorkspaceOut, status_code=201)
async def create_workspace(
    body: WorkspaceIn,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> WorkspaceOut:
    now = datetime.now(UTC)
    workspace = Workspace(name=body.name, slug=body.slug, created_at=now, updated_at=now)
    session.add(workspace)
    await session.flush()
    session.add(
        Membership(
            user_id=user.id,
            workspace_id=workspace.id,
            role="owner",
            created_at=now,
        )
    )
    await session.flush()
    return workspace_out(workspace)


@router.get("", response_model=list[WorkspaceOut])
async def list_workspaces(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[WorkspaceOut]:
    rows = (
        await session.scalars(
            select(Workspace)
            .join(Membership, Membership.workspace_id == Workspace.id)
            .where(Membership.user_id == user.id)
            .order_by(Workspace.id)
        )
    ).all()
    return [workspace_out(row) for row in rows]


@router.get("/{workspace_id}", response_model=WorkspaceOut)
async def get_workspace(
    workspace_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> WorkspaceOut:
    await require_workspace(session, user, workspace_id)
    workspace = await session.get(Workspace, workspace_id)
    if workspace is None:
        raise APIError(404, "not_found", "Workspace not found")
    return workspace_out(workspace)


@router.patch("/{workspace_id}", response_model=WorkspaceOut)
async def update_workspace(
    workspace_id: int,
    body: WorkspaceUpdate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> WorkspaceOut:
    membership = await require_workspace(session, user, workspace_id)
    if membership.role != "owner":
        raise APIError(403, "forbidden", "Only the workspace owner can update it")
    workspace = await session.get(Workspace, workspace_id)
    if workspace is None:
        raise APIError(404, "not_found", "Workspace not found")
    if body.name is not None:
        workspace.name = body.name
        workspace.updated_at = datetime.now(UTC)
    return workspace_out(workspace)


@router.delete("/{workspace_id}", status_code=204)
async def delete_workspace(
    workspace_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> Response:
    membership = await require_workspace(session, user, workspace_id)
    if membership.role != "owner":
        raise APIError(403, "forbidden", "Only the workspace owner can delete it")
    workspace = await session.get(Workspace, workspace_id)
    if workspace is None:
        raise APIError(404, "not_found", "Workspace not found")
    await session.delete(workspace)
    return Response(status_code=204)


@router.post("/{workspace_id}/members", response_model=MemberOut, status_code=201)
async def add_member(
    workspace_id: int,
    body: MemberIn,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> MemberOut:
    membership = await require_workspace(session, user, workspace_id)
    if membership.role != "owner":
        raise APIError(403, "forbidden", "Only the workspace owner can add members")
    other = await session.get(User, body.user_id)
    if other is None:
        raise APIError(404, "not_found", "User not found")
    already = await session.scalar(
        select(Membership).where(
            Membership.user_id == other.id,
            Membership.workspace_id == workspace_id,
        )
    )
    if already is not None:
        raise APIError(409, "conflict", "User is already a member")
    created = Membership(
        user_id=other.id,
        workspace_id=workspace_id,
        role="member",
        created_at=datetime.now(UTC),
    )
    session.add(created)
    await session.flush()
    return member_out(created)


@router.get("/{workspace_id}/members", response_model=list[MemberOut])
async def list_members(
    workspace_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[MemberOut]:
    await require_workspace(session, user, workspace_id)
    rows = (
        await session.scalars(
            select(Membership)
            .where(Membership.workspace_id == workspace_id)
            .order_by(Membership.user_id)
        )
    ).all()
    return [member_out(row) for row in rows]

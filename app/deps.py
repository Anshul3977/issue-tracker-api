"""Request dependencies: session, current user, membership checks."""

from __future__ import annotations

from fastapi import Depends, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import hash_api_key
from app.db import get_session
from app.errors import APIError
from app.models import Label, Membership, Project, User


async def get_current_user(
    session: AsyncSession = Depends(get_session),
    api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> User:
    if not api_key:
        raise APIError(401, "unauthorized", "Missing API key")
    user = await session.scalar(select(User).where(User.api_key_hash == hash_api_key(api_key)))
    if user is None:
        raise APIError(401, "unauthorized", "Invalid API key")
    return user


async def require_workspace(session: AsyncSession, user: User, workspace_id: int) -> Membership:
    membership = await session.scalar(
        select(Membership).where(
            Membership.user_id == user.id,
            Membership.workspace_id == workspace_id,
        )
    )
    if membership is None:
        raise APIError(404, "not_found", "Workspace not found")
    return membership


async def require_project(session: AsyncSession, user: User, project_id: int) -> Project:
    project = await session.get(Project, project_id)
    if project is None:
        raise APIError(404, "not_found", "Project not found")
    await require_workspace(session, user, project.workspace_id)
    return project


async def labels_for_project(
    session: AsyncSession, project_id: int, label_ids: list[int]
) -> list[Label]:
    if not label_ids:
        return []
    unique_ids = list(dict.fromkeys(label_ids))
    rows = list(
        await session.scalars(
            select(Label).where(Label.project_id == project_id, Label.id.in_(unique_ids))
        )
    )
    if len(rows) != len(unique_ids):
        raise APIError(422, "invalid_label", "One or more labels do not belong to the project")
    return rows


async def ensure_assignee(
    session: AsyncSession, workspace_id: int, assignee_id: int | None
) -> None:
    if assignee_id is None:
        return
    member = await session.scalar(
        select(Membership.user_id).where(
            Membership.user_id == assignee_id,
            Membership.workspace_id == workspace_id,
        )
    )
    if member is None:
        raise APIError(422, "invalid_assignee", "Assignee is not a member of the workspace")

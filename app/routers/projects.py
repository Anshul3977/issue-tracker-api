"""Projects, labels, and cached issue counts."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache import cache_get, cache_set, counts_cache_key, invalidate_issue_write
from app.db import get_session
from app.deps import get_current_user, require_project, require_workspace
from app.models import STATES, Issue, Label, Project, User
from app.present import label_out, project_out
from app.schemas import IssueCounts, LabelIn, LabelOut, ProjectIn, ProjectOut, ProjectUpdate

router = APIRouter(tags=["projects"])


@router.post("/projects", response_model=ProjectOut, status_code=201)
async def create_project(
    body: ProjectIn,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> ProjectOut:
    await require_workspace(session, user, body.workspace_id)
    now = datetime.now(UTC)
    project = Project(
        workspace_id=body.workspace_id,
        name=body.name,
        key=body.key,
        description=body.description,
        issue_counter=0,
        created_at=now,
        updated_at=now,
    )
    session.add(project)
    await session.flush()
    return project_out(project)


@router.get("/projects", response_model=list[ProjectOut])
async def list_projects(
    workspace_id: int = Query(),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[ProjectOut]:
    await require_workspace(session, user, workspace_id)
    rows = (
        await session.scalars(
            select(Project).where(Project.workspace_id == workspace_id).order_by(Project.id)
        )
    ).all()
    return [project_out(row) for row in rows]


@router.get("/projects/{project_id}", response_model=ProjectOut)
async def get_project(
    project_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> ProjectOut:
    project = await require_project(session, user, project_id)
    return project_out(project)


@router.patch("/projects/{project_id}", response_model=ProjectOut)
async def update_project(
    project_id: int,
    body: ProjectUpdate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> ProjectOut:
    project = await require_project(session, user, project_id)
    if body.name is not None:
        project.name = body.name
    if body.description is not None:
        project.description = body.description
    if body.model_fields_set:
        project.updated_at = datetime.now(UTC)
    return project_out(project)


@router.delete("/projects/{project_id}", status_code=204)
async def delete_project(
    project_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> Response:
    project = await require_project(session, user, project_id)
    await session.delete(project)
    await session.commit()
    await invalidate_issue_write(project_id, None)
    return Response(status_code=204)


@router.get("/projects/{project_id}/issue-counts", response_model=IssueCounts)
async def issue_counts(
    project_id: int,
    response: Response,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> IssueCounts | JSONResponse:
    await require_project(session, user, project_id)
    key = counts_cache_key(project_id)
    cached = await cache_get(key)
    if cached is not None:
        response.headers["X-Cache"] = "HIT"
        return IssueCounts.model_validate_json(cached)
    grouped = await session.execute(
        select(Issue.state, func.count())
        .where(Issue.project_id == project_id)
        .group_by(Issue.state)
    )
    counts = {state: 0 for state in STATES}
    total = 0
    for state, count in grouped.all():
        counts[str(state)] = int(count)
        total += int(count)
    payload = IssueCounts(project_id=project_id, counts=counts, total=total)
    await cache_set(key, payload.model_dump_json())
    response.headers["X-Cache"] = "MISS"
    return payload


@router.post("/projects/{project_id}/labels", response_model=LabelOut, status_code=201)
async def create_label(
    project_id: int,
    body: LabelIn,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> LabelOut:
    await require_project(session, user, project_id)
    label = Label(project_id=project_id, name=body.name, color=body.color.lower())
    session.add(label)
    await session.flush()
    return label_out(label)


@router.get("/projects/{project_id}/labels", response_model=list[LabelOut])
async def list_labels(
    project_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[LabelOut]:
    await require_project(session, user, project_id)
    rows = (
        await session.scalars(
            select(Label).where(Label.project_id == project_id).order_by(Label.id)
        )
    ).all()
    return [label_out(row) for row in rows]

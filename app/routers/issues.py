"""Issue CRUD and the keyset list endpoint."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import set_committed_value

from app.cache import cache_get, cache_set, invalidate_issue_write, issue_cache_key
from app.db import get_session
from app.deps import (
    ensure_assignee,
    get_current_user,
    labels_for_project,
    require_project,
)
from app.errors import APIError
from app.models import Issue, Project, User
from app.present import issue_out
from app.pubsub import bus, dump_event
from app.queries import decode_cursor, encode_cursor, issue_list_select
from app.schemas import IssueIn, IssueOut, IssuePage, IssueState, IssueUpdate, SortField

router = APIRouter(prefix="/issues", tags=["issues"])

CACHE_HEADER = {
    "description": "HIT when served from Redis, MISS when loaded from Postgres and stored.",
    "schema": {"type": "string", "enum": ["HIT", "MISS"]},
}


async def _load_issue(session: AsyncSession, issue_id: int) -> Issue:
    issue = await session.scalar(
        select(Issue).where(Issue.id == issue_id).options(selectinload(Issue.labels))
    )
    if issue is None:
        raise APIError(404, "not_found", "Issue not found")
    return issue


async def _publish_issue(event_type: str, issue: IssueOut) -> None:
    await bus.publish(
        issue.project_id,
        dump_event(event_type, issue.project_id, issue.model_dump(mode="json")),
    )


@router.post("", response_model=IssueOut, status_code=201)
async def create_issue(
    body: IssueIn,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> IssueOut:
    project = await require_project(session, user, body.project_id)
    locked = await session.scalar(select(Project).where(Project.id == project.id).with_for_update())
    if locked is None:
        raise APIError(404, "not_found", "Project not found")
    await ensure_assignee(session, locked.workspace_id, body.assignee_id)
    labels = await labels_for_project(session, locked.id, body.label_ids)
    now = datetime.now(UTC)
    locked.issue_counter += 1
    issue = Issue(
        project_id=locked.id,
        number=locked.issue_counter,
        title=body.title,
        description=body.description,
        state=body.state.value,
        priority=body.priority.value,
        assignee_id=body.assignee_id,
        created_at=now,
        updated_at=now,
    )
    session.add(issue)
    await session.flush()
    # lazy="raise" refuses to load the old collection during assignment.
    # Mark it loaded and empty, then assign so the association rows are inserted.
    set_committed_value(issue, "labels", [])
    issue.labels = labels
    await session.flush()
    await session.commit()
    payload = issue_out(issue)
    await invalidate_issue_write(locked.id, issue.id)
    await _publish_issue("issue.created", payload)
    return payload


@router.get("", response_model=IssuePage)
async def list_issues(
    project_id: int = Query(),
    state: IssueState | None = None,
    assignee_id: int | None = None,
    label_id: int | None = None,
    sort: SortField = "created_at",
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = None,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> IssuePage:
    """Keyset page of issues.

    ``sort=created_at`` with ``project_id`` and ``state`` is the indexed path
    measured in ``benchmarks/``. One extra row is fetched to decide
    ``next_cursor`` without a second count query.
    """

    await require_project(session, user, project_id)
    decoded = decode_cursor(cursor) if cursor else None
    stmt = issue_list_select(
        project_id=project_id,
        state=state.value if state is not None else None,
        assignee_id=assignee_id,
        label_id=label_id,
        sort=sort,
        cursor=decoded,
        limit=limit + 1,
    )
    rows = list((await session.scalars(stmt)).all())
    has_more = len(rows) > limit
    page = rows[:limit]
    next_cursor = None
    if has_more and page:
        last = page[-1]
        moment = last.created_at if sort == "created_at" else last.updated_at
        next_cursor = encode_cursor(moment, last.id)
    return IssuePage(items=[issue_out(row) for row in page], next_cursor=next_cursor)


@router.get(
    "/{issue_id}",
    response_model=IssueOut,
    responses={200: {"headers": {"X-Cache": CACHE_HEADER}}},
)
async def get_issue(
    issue_id: int,
    response: Response,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> IssueOut:
    key = issue_cache_key(issue_id)
    cached = await cache_get(key)
    if cached is not None:
        payload = IssueOut.model_validate_json(cached)
        await require_project(session, user, payload.project_id)
        response.headers["X-Cache"] = "HIT"
        return payload
    issue = await _load_issue(session, issue_id)
    await require_project(session, user, issue.project_id)
    payload = issue_out(issue)
    await cache_set(key, payload.model_dump_json())
    response.headers["X-Cache"] = "MISS"
    return payload


@router.patch("/{issue_id}", response_model=IssueOut)
async def update_issue(
    issue_id: int,
    body: IssueUpdate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> IssueOut:
    issue = await _load_issue(session, issue_id)
    project = await require_project(session, user, issue.project_id)
    provided = body.model_fields_set
    if "assignee_id" in provided:
        await ensure_assignee(session, project.workspace_id, body.assignee_id)
        issue.assignee_id = body.assignee_id
    if body.title is not None:
        issue.title = body.title
    if body.description is not None:
        issue.description = body.description
    if body.state is not None:
        issue.state = body.state.value
    if body.priority is not None:
        issue.priority = body.priority.value
    if body.label_ids is not None:
        issue.labels = await labels_for_project(session, issue.project_id, body.label_ids)
    issue.updated_at = datetime.now(UTC)
    await session.commit()
    payload = issue_out(issue)
    await invalidate_issue_write(issue.project_id, issue.id)
    await _publish_issue("issue.updated", payload)
    return payload


@router.delete("/{issue_id}", status_code=204)
async def delete_issue(
    issue_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> Response:
    issue = await _load_issue(session, issue_id)
    await require_project(session, user, issue.project_id)
    payload = issue_out(issue)
    await session.delete(issue)
    await session.commit()
    await invalidate_issue_write(payload.project_id, payload.id)
    await _publish_issue("issue.deleted", payload)
    return Response(status_code=204)

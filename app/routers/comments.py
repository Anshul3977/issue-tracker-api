"""Issue comments."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import get_current_user, require_project
from app.errors import APIError
from app.models import Comment, Issue, User
from app.present import comment_out
from app.pubsub import bus, dump_event
from app.queries import decode_cursor, encode_cursor
from app.schemas import CommentIn, CommentOut, CommentPage

router = APIRouter(prefix="/issues/{issue_id}/comments", tags=["comments"])


@router.post("", response_model=CommentOut, status_code=201)
async def create_comment(
    issue_id: int,
    body: CommentIn,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> CommentOut:
    issue = await session.get(Issue, issue_id)
    if issue is None:
        raise APIError(404, "not_found", "Issue not found")
    await require_project(session, user, issue.project_id)
    now = datetime.now(UTC)
    comment = Comment(
        issue_id=issue.id,
        author_id=user.id,
        body=body.body,
        created_at=now,
        updated_at=now,
    )
    session.add(comment)
    await session.flush()
    await session.commit()
    payload = comment_out(comment)
    await bus.publish(
        issue.project_id,
        dump_event("comment.created", issue.project_id, payload.model_dump(mode="json")),
    )
    return payload


@router.get("", response_model=CommentPage)
async def list_comments(
    issue_id: int,
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = None,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> CommentPage:
    issue = await session.get(Issue, issue_id)
    if issue is None:
        raise APIError(404, "not_found", "Issue not found")
    await require_project(session, user, issue.project_id)
    stmt = select(Comment).where(Comment.issue_id == issue.id)
    if cursor is not None:
        moment, row_id = decode_cursor(cursor)
        stmt = stmt.where(
            or_(
                Comment.created_at > moment, and_(Comment.created_at == moment, Comment.id > row_id)
            )
        )
    stmt = stmt.order_by(Comment.created_at.asc(), Comment.id.asc()).limit(limit + 1)
    rows = list((await session.scalars(stmt)).all())
    has_more = len(rows) > limit
    page = rows[:limit]
    next_cursor = encode_cursor(page[-1].created_at, page[-1].id) if has_more and page else None
    return CommentPage(items=[comment_out(row) for row in page], next_cursor=next_cursor)

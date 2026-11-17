"""Issue list statement.

The benchmark explains and loads this statement. Column order matches
``ix_issues_project_state_created_id``: equality on project and state, then
``created_at DESC, id DESC`` for the keyset order. Authorization is a separate
point lookup so this statement stays a single-table index scan.
"""

from __future__ import annotations

import base64
from datetime import datetime
from typing import Any

from sqlalchemy import Select, and_, or_, select
from sqlalchemy.orm import selectinload

from app.errors import APIError
from app.models import Issue, IssueLabel
from app.schemas import SortField


def encode_cursor(moment: datetime, row_id: int) -> str:
    if moment.tzinfo is None:
        raise ValueError("cursor timestamp must be timezone-aware")
    raw = f"{moment.isoformat()}|{row_id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(raw: str) -> tuple[datetime, int]:
    try:
        padded = raw + ("=" * (-len(raw) % 4))
        text = base64.urlsafe_b64decode(padded.encode()).decode()
        stamp, row_id = text.split("|", 1)
        moment = datetime.fromisoformat(stamp)
        if moment.tzinfo is None:
            raise ValueError("naive timestamp")
        return moment, int(row_id)
    except Exception as exc:
        raise APIError(400, "bad_cursor", "Invalid cursor") from exc


def issue_list_select(
    *,
    project_id: int,
    state: str | None,
    assignee_id: int | None,
    label_id: int | None,
    sort: SortField,
    cursor: tuple[datetime, int] | None,
    limit: int,
) -> Select[Any]:
    sort_col = Issue.created_at if sort == "created_at" else Issue.updated_at
    stmt = select(Issue).where(Issue.project_id == project_id)
    if state is not None:
        stmt = stmt.where(Issue.state == state)
    if assignee_id is not None:
        stmt = stmt.where(Issue.assignee_id == assignee_id)
    if label_id is not None:
        label_ids = select(IssueLabel.issue_id).where(IssueLabel.label_id == label_id)
        stmt = stmt.where(Issue.id.in_(label_ids))
    if cursor is not None:
        moment, row_id = cursor
        stmt = stmt.where(or_(sort_col < moment, and_(sort_col == moment, Issue.id < row_id)))
    stmt = stmt.order_by(sort_col.desc(), Issue.id.desc()).limit(limit)
    return stmt.options(selectinload(Issue.labels))

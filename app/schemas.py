"""Request and response models."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class IssueState(StrEnum):
    backlog = "backlog"
    todo = "todo"
    in_progress = "in_progress"
    done = "done"
    cancelled = "cancelled"


class IssuePriority(StrEnum):
    none = "none"
    low = "low"
    medium = "medium"
    high = "high"
    urgent = "urgent"


class APIModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RegisterIn(APIModel):
    email: str = Field(min_length=3, max_length=320)
    name: str = Field(min_length=1, max_length=120)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        email = value.strip().lower()
        if "@" not in email or email.startswith("@") or email.endswith("@"):
            raise ValueError("invalid email")
        return email

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        name = value.strip()
        if not name:
            raise ValueError("must not be blank")
        return name


class UserOut(BaseModel):
    id: int
    email: str
    name: str
    created_at: datetime


class RegisterOut(BaseModel):
    user: UserOut
    api_key: str


class WorkspaceIn(APIModel):
    name: str = Field(min_length=1, max_length=120)
    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=60)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        name = value.strip()
        if not name:
            raise ValueError("must not be blank")
        return name


class WorkspaceUpdate(APIModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        name = value.strip()
        if not name:
            raise ValueError("must not be blank")
        return name


class WorkspaceOut(BaseModel):
    id: int
    name: str
    slug: str
    created_at: datetime
    updated_at: datetime


class MemberIn(APIModel):
    user_id: int


class MemberOut(BaseModel):
    user_id: int
    workspace_id: int
    role: str
    created_at: datetime


class ProjectIn(APIModel):
    workspace_id: int
    name: str = Field(min_length=1, max_length=120)
    key: str = Field(pattern=r"^[A-Z][A-Z0-9]{1,9}$")
    description: str = Field(default="", max_length=20000)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        name = value.strip()
        if not name:
            raise ValueError("must not be blank")
        return name

    @field_validator("description")
    @classmethod
    def strip_description(cls, value: str) -> str:
        return value.strip()


class ProjectUpdate(APIModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=20000)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        name = value.strip()
        if not name:
            raise ValueError("must not be blank")
        return name

    @field_validator("description")
    @classmethod
    def strip_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip()


class ProjectOut(BaseModel):
    id: int
    workspace_id: int
    name: str
    key: str
    description: str
    issue_counter: int
    created_at: datetime
    updated_at: datetime


class LabelIn(APIModel):
    name: str = Field(min_length=1, max_length=40)
    color: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        name = value.strip()
        if not name:
            raise ValueError("must not be blank")
        return name


class LabelOut(BaseModel):
    id: int
    project_id: int
    name: str
    color: str


class IssueIn(APIModel):
    project_id: int
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=20000)
    state: IssueState = IssueState.todo
    priority: IssuePriority = IssuePriority.none
    assignee_id: int | None = None
    label_ids: list[int] = Field(default_factory=list, max_length=20)

    @field_validator("title")
    @classmethod
    def strip_title(cls, value: str) -> str:
        title = value.strip()
        if not title:
            raise ValueError("must not be blank")
        return title

    @field_validator("description")
    @classmethod
    def strip_description(cls, value: str) -> str:
        return value.strip()


class IssueUpdate(APIModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=20000)
    state: IssueState | None = None
    priority: IssuePriority | None = None
    assignee_id: int | None = None
    label_ids: list[int] | None = Field(default=None, max_length=20)

    @field_validator("title")
    @classmethod
    def strip_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        title = value.strip()
        if not title:
            raise ValueError("must not be blank")
        return title

    @field_validator("description")
    @classmethod
    def strip_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip()


class IssueOut(BaseModel):
    id: int
    project_id: int
    number: int
    title: str
    description: str
    state: IssueState
    priority: IssuePriority
    assignee_id: int | None
    label_ids: list[int]
    created_at: datetime
    updated_at: datetime


class IssuePage(BaseModel):
    items: list[IssueOut]
    next_cursor: str | None


class IssueCounts(BaseModel):
    project_id: int
    counts: dict[str, int]
    total: int


class CommentIn(APIModel):
    body: str = Field(min_length=1, max_length=10000)

    @field_validator("body")
    @classmethod
    def strip_body(cls, value: str) -> str:
        body = value.strip()
        if not body:
            raise ValueError("must not be blank")
        return body


class CommentOut(BaseModel):
    id: int
    issue_id: int
    author_id: int
    body: str
    created_at: datetime
    updated_at: datetime


class CommentPage(BaseModel):
    items: list[CommentOut]
    next_cursor: str | None


SortField = Literal["created_at", "updated_at"]

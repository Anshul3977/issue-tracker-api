"""Relational model.

Issue ids are bigints. The list endpoint orders by ``(created_at, id)`` and the
composite index ``ix_issues_project_state_created_id`` matches that order for a
single project and state. See ``sql/ix_issues_project_state_created_id.sql``.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    desc,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

STATES = ("backlog", "todo", "in_progress", "done", "cancelled")
PRIORITIES = ("none", "low", "medium", "high", "urgent")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    api_key_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(60), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (
        CheckConstraint("role IN ('owner', 'member')", name="ck_memberships_role"),
        Index("ix_memberships_workspace_id", "workspace_id"),
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (
        UniqueConstraint("workspace_id", "key", name="uq_projects_workspace_key"),
        Index("ix_projects_workspace_id", "workspace_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    key: Mapped[str] = mapped_column(String(10), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    issue_counter: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Label(Base):
    __tablename__ = "labels"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_labels_project_name"),
        Index("ix_labels_project_id", "project_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(40), nullable=False)
    color: Mapped[str] = mapped_column(String(7), nullable=False)


class Issue(Base):
    __tablename__ = "issues"
    __table_args__ = (
        UniqueConstraint("project_id", "number", name="uq_issues_project_number"),
        CheckConstraint(
            "state IN ('backlog', 'todo', 'in_progress', 'done', 'cancelled')",
            name="ck_issues_state",
        ),
        CheckConstraint(
            "priority IN ('none', 'low', 'medium', 'high', 'urgent')",
            name="ck_issues_priority",
        ),
        Index("ix_issues_project_id", "project_id"),
        Index("ix_issues_assignee_id", "assignee_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    priority: Mapped[str] = mapped_column(String(16), nullable=False, server_default="none")
    assignee_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    labels: Mapped[list[Label]] = relationship(
        secondary="issue_labels",
        lazy="raise",
    )


Index(
    "ix_issues_project_state_created_id",
    Issue.project_id,
    Issue.state,
    desc(Issue.created_at),  # type: ignore[arg-type]
    desc(Issue.id),  # type: ignore[arg-type]
)


class IssueLabel(Base):
    __tablename__ = "issue_labels"
    __table_args__ = (Index("ix_issue_labels_label_id", "label_id"),)

    issue_id: Mapped[int] = mapped_column(
        ForeignKey("issues.id", ondelete="CASCADE"), primary_key=True
    )
    label_id: Mapped[int] = mapped_column(
        ForeignKey("labels.id", ondelete="CASCADE"), primary_key=True
    )


class Comment(Base):
    __tablename__ = "comments"
    __table_args__ = (Index("ix_comments_issue_id_created_at_id", "issue_id", "created_at", "id"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    issue_id: Mapped[int] = mapped_column(
        ForeignKey("issues.id", ondelete="CASCADE"), nullable=False
    )
    author_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

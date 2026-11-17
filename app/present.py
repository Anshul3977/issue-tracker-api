"""ORM rows to response models."""

from __future__ import annotations

from app.models import Comment, Issue, Label, Membership, Project, User, Workspace
from app.schemas import (
    CommentOut,
    IssueOut,
    IssuePriority,
    IssueState,
    LabelOut,
    MemberOut,
    ProjectOut,
    UserOut,
    WorkspaceOut,
)


def user_out(user: User) -> UserOut:
    return UserOut(id=user.id, email=user.email, name=user.name, created_at=user.created_at)


def workspace_out(workspace: Workspace) -> WorkspaceOut:
    return WorkspaceOut(
        id=workspace.id,
        name=workspace.name,
        slug=workspace.slug,
        created_at=workspace.created_at,
        updated_at=workspace.updated_at,
    )


def member_out(membership: Membership) -> MemberOut:
    return MemberOut(
        user_id=membership.user_id,
        workspace_id=membership.workspace_id,
        role=membership.role,
        created_at=membership.created_at,
    )


def project_out(project: Project) -> ProjectOut:
    return ProjectOut(
        id=project.id,
        workspace_id=project.workspace_id,
        name=project.name,
        key=project.key,
        description=project.description,
        issue_counter=project.issue_counter,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


def label_out(label: Label) -> LabelOut:
    return LabelOut(id=label.id, project_id=label.project_id, name=label.name, color=label.color)


def issue_out(issue: Issue) -> IssueOut:
    return IssueOut(
        id=issue.id,
        project_id=issue.project_id,
        number=issue.number,
        title=issue.title,
        description=issue.description,
        state=IssueState(issue.state),
        priority=IssuePriority(issue.priority),
        assignee_id=issue.assignee_id,
        label_ids=sorted(label.id for label in issue.labels),
        created_at=issue.created_at,
        updated_at=issue.updated_at,
    )


def comment_out(comment: Comment) -> CommentOut:
    return CommentOut(
        id=comment.id,
        issue_id=comment.issue_id,
        author_id=comment.author_id,
        body=comment.body,
        created_at=comment.created_at,
        updated_at=comment.updated_at,
    )

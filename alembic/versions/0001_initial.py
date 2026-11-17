"""Initial schema, including the list-query index.

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-16
"""

from pathlib import Path

import sqlalchemy as sa

from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

INDEX_SQL = (
    Path(__file__).resolve().parents[2] / "sql" / "ix_issues_project_state_created_id.sql"
).read_text()


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("api_key_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.UniqueConstraint("api_key_hash", name="uq_users_api_key_hash"),
    )
    op.create_table(
        "workspaces",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("slug", sa.String(length=60), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("slug", name="uq_workspaces_slug"),
    )
    op.create_table(
        "memberships",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("role IN ('owner', 'member')", name="ck_memberships_role"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "workspace_id"),
    )
    op.create_index("ix_memberships_workspace_id", "memberships", ["workspace_id"])
    op.create_table(
        "projects",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("key", sa.String(length=10), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("issue_counter", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("workspace_id", "key", name="uq_projects_workspace_key"),
    )
    op.create_index("ix_projects_workspace_id", "projects", ["workspace_id"])
    op.create_table(
        "labels",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("project_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=40), nullable=False),
        sa.Column("color", sa.String(length=7), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("project_id", "name", name="uq_labels_project_name"),
    )
    op.create_index("ix_labels_project_id", "labels", ["project_id"])
    op.create_table(
        "issues",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("project_id", sa.BigInteger(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("priority", sa.String(length=16), server_default="none", nullable=False),
        sa.Column("assignee_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "state IN ('backlog', 'todo', 'in_progress', 'done', 'cancelled')",
            name="ck_issues_state",
        ),
        sa.CheckConstraint(
            "priority IN ('none', 'low', 'medium', 'high', 'urgent')",
            name="ck_issues_priority",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assignee_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("project_id", "number", name="uq_issues_project_number"),
    )
    op.create_index("ix_issues_project_id", "issues", ["project_id"])
    op.create_index("ix_issues_assignee_id", "issues", ["assignee_id"])
    op.execute(INDEX_SQL)
    op.create_table(
        "issue_labels",
        sa.Column("issue_id", sa.BigInteger(), nullable=False),
        sa.Column("label_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["issue_id"], ["issues.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["label_id"], ["labels.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("issue_id", "label_id"),
    )
    op.create_index("ix_issue_labels_label_id", "issue_labels", ["label_id"])
    op.create_table(
        "comments",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("issue_id", sa.BigInteger(), nullable=False),
        sa.Column("author_id", sa.BigInteger(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["issue_id"], ["issues.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_comments_issue_id_created_at_id",
        "comments",
        ["issue_id", "created_at", "id"],
    )


def downgrade() -> None:
    op.drop_table("comments")
    op.drop_table("issue_labels")
    op.execute("DROP INDEX IF EXISTS ix_issues_project_state_created_id")
    op.drop_table("issues")
    op.drop_table("labels")
    op.drop_table("projects")
    op.drop_table("memberships")
    op.drop_table("workspaces")
    op.drop_table("users")

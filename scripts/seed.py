"""Load a deterministic synthetic dataset for the index benchmark.

The row count and random seed are fixed. Re-running is a no-op unless ``--force``
is passed or the loaded dataset does not match this version.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import random
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.auth import hash_api_key  # noqa: E402
from app.config import get_settings  # noqa: E402

SEED_VERSION = 1
ISSUE_COUNT = 500_000
COMMENT_COUNT = 20_000
USER_COUNT = 40
CHUNK = 20_000
PROJECTS = (
    ("CORE", "Core"),
    ("API", "API"),
    ("WEB", "Web"),
    ("OPS", "Ops"),
    ("MOB", "Mobile"),
    ("DOC", "Docs"),
    ("INF", "Infra"),
    ("QA", "Quality"),
)
LABELS = (
    ("bug", "#c2410c"),
    ("feature", "#2563eb"),
    ("perf", "#15803d"),
    ("docs", "#a16207"),
    ("chore", "#57534e"),
)
EPOCH = datetime(2024, 1, 1, tzinfo=UTC)
SPAN_SECONDS = 400 * 24 * 3600


def _state(roll: int) -> str:
    if roll < 20:
        return "backlog"
    if roll < 50:
        return "todo"
    if roll < 70:
        return "in_progress"
    if roll < 95:
        return "done"
    return "cancelled"


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if os.environ.get("APP_ENV") == "test":
        raise SystemExit("refusing to seed when APP_ENV=test")

    import asyncpg

    settings = get_settings()
    dsn = settings.async_database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    api_key = os.environ.get("SEED_API_KEY", "local-dev-api-key")
    started = time.perf_counter()
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS seed_meta (
                id integer PRIMARY KEY,
                seed_version integer NOT NULL,
                issue_count integer NOT NULL,
                seeded_at timestamptz NOT NULL
            )
            """
        )
        existing = await conn.fetchrow(
            "SELECT seed_version, issue_count FROM seed_meta WHERE id = 1"
        )
        actual = await conn.fetchval("SELECT count(*) FROM issues")
        if (
            not args.force
            and existing is not None
            and existing["seed_version"] == SEED_VERSION
            and existing["issue_count"] == ISSUE_COUNT
            and actual == ISSUE_COUNT
        ):
            project_id = await conn.fetchval("SELECT id FROM projects WHERE key = 'CORE'")
            print(f"seed already loaded issues={actual} core_project_id={project_id}")
            return

        await conn.execute(
            """
            TRUNCATE comments, issue_labels, issues, labels, projects,
                     memberships, workspaces, users RESTART IDENTITY CASCADE
            """
        )
        now = datetime.now(UTC)
        user_rows = [
            (f"user{i}@example.com", f"User {i}", hash_api_key(f"seed-user-{i}"))
            for i in range(2, USER_COUNT + 1)
        ]
        await conn.execute(
            "INSERT INTO users (email, name, api_key_hash, created_at) VALUES ($1, $2, $3, $4)",
            "bench@example.com",
            "Bench User",
            hash_api_key(api_key),
            now,
        )
        await conn.executemany(
            "INSERT INTO users (email, name, api_key_hash, created_at) VALUES ($1, $2, $3, $4)",
            [(email, name, digest, now) for email, name, digest in user_rows],
        )
        workspace_id = await conn.fetchval(
            """
            INSERT INTO workspaces (name, slug, created_at, updated_at)
            VALUES ('Plane Lab', 'plane-lab', $1, $1)
            RETURNING id
            """,
            now,
        )
        await conn.executemany(
            """
            INSERT INTO memberships (user_id, workspace_id, role, created_at)
            VALUES ($1, $2, $3, $4)
            """,
            [
                (1, workspace_id, "owner", now),
                *[(user_id, workspace_id, "member", now) for user_id in range(2, USER_COUNT + 1)],
            ],
        )
        project_ids: list[int] = []
        for key, name in PROJECTS:
            project_id = await conn.fetchval(
                """
                INSERT INTO projects
                    (workspace_id, name, key, description, issue_counter, created_at, updated_at)
                VALUES ($1, $2, $3, '', 0, $4, $4)
                RETURNING id
                """,
                workspace_id,
                name,
                key,
                now,
            )
            project_ids.append(project_id)
        labels_by_project: dict[int, list[int]] = {}
        for project_id in project_ids:
            label_ids = []
            for name, color in LABELS:
                label_id = await conn.fetchval(
                    """
                    INSERT INTO labels (project_id, name, color)
                    VALUES ($1, $2, $3)
                    RETURNING id
                    """,
                    project_id,
                    name,
                    color,
                )
                label_ids.append(label_id)
            labels_by_project[project_id] = label_ids

        rng = random.Random(42)
        priorities = ("none", "low", "medium", "high", "urgent")
        counters = [0] * len(project_ids)
        labeled: list[tuple[int, int]] = []
        chunk: list[tuple] = []
        columns = [
            "project_id",
            "number",
            "title",
            "description",
            "state",
            "priority",
            "assignee_id",
            "created_at",
            "updated_at",
        ]
        for number in range(1, ISSUE_COUNT + 1):
            if rng.randrange(100) < 70:
                index = 0
            else:
                index = 1 + rng.randrange(len(project_ids) - 1)
            counters[index] += 1
            state = _state(rng.randrange(100))
            priority = priorities[rng.randrange(5)]
            assignee = 1 + rng.randrange(USER_COUNT) if rng.randrange(100) < 80 else None
            created = EPOCH + timedelta(seconds=rng.randrange(SPAN_SECONDS))
            project_id = project_ids[index]
            chunk.append(
                (
                    project_id,
                    counters[index],
                    f"Issue {counters[index]}",
                    f"Synthetic issue {counters[index]} for project {project_id}. Seed 42.",
                    state,
                    priority,
                    assignee,
                    created,
                    created,
                )
            )
            if number % 50 == 0:
                labeled.append((number, project_id))
            if len(chunk) >= CHUNK:
                await conn.copy_records_to_table("issues", records=chunk, columns=columns)
                print(f"copied issues {number}", flush=True)
                chunk = []
        if chunk:
            await conn.copy_records_to_table("issues", records=chunk, columns=columns)

        await conn.executemany(
            "INSERT INTO issue_labels (issue_id, label_id) VALUES ($1, $2)",
            [
                (issue_id, labels_by_project[project_id][issue_id % len(LABELS)])
                for issue_id, project_id in labeled
            ],
        )
        comment_rng = random.Random(7)
        comments = []
        for index in range(COMMENT_COUNT):
            created = EPOCH + timedelta(seconds=comment_rng.randrange(SPAN_SECONDS))
            comments.append(
                (
                    1 + comment_rng.randrange(ISSUE_COUNT),
                    1 + comment_rng.randrange(USER_COUNT),
                    f"Comment {index} on the synthetic dataset.",
                    created,
                    created,
                )
            )
        await conn.copy_records_to_table(
            "comments",
            records=comments,
            columns=["issue_id", "author_id", "body", "created_at", "updated_at"],
        )
        await conn.execute(
            """
            UPDATE projects AS project
            SET issue_counter = counted.n
            FROM (
                SELECT project_id, count(*)::int AS n
                FROM issues
                GROUP BY project_id
            ) AS counted
            WHERE project.id = counted.project_id
            """
        )
        await conn.execute(
            """
            INSERT INTO seed_meta (id, seed_version, issue_count, seeded_at)
            VALUES (1, $1, $2, now())
            ON CONFLICT (id) DO UPDATE
            SET seed_version = EXCLUDED.seed_version,
                issue_count = EXCLUDED.issue_count,
                seeded_at = EXCLUDED.seeded_at
            """,
            SEED_VERSION,
            ISSUE_COUNT,
        )
        await conn.execute("VACUUM (ANALYZE) issues")
        await conn.execute("ANALYZE comments")
        await conn.execute("ANALYZE issue_labels")
        core_id = await conn.fetchval("SELECT id FROM projects WHERE key = 'CORE'")
        todo = await conn.fetchval(
            "SELECT count(*) FROM issues WHERE project_id = $1 AND state = 'todo'",
            core_id,
        )
        elapsed = time.perf_counter() - started
        print(
            f"seeded issues={ISSUE_COUNT} comments={COMMENT_COUNT} "
            f"core_project_id={core_id} core_todo={todo} seconds={elapsed:.3f}"
        )
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())

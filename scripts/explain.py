"""Run EXPLAIN (ANALYZE, BUFFERS) for the issue list statement the API executes."""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import text  # noqa: E402

from app.db import SessionLocal, engine  # noqa: E402
from app.queries import issue_list_select  # noqa: E402


async def _plan(connection, statement) -> str:  # type: ignore[no-untyped-def]
    compiled = statement.compile(dialect=connection.dialect)
    raw = await connection.get_raw_connection()
    driver = raw.driver_connection
    names = compiled.positiontup or ()
    args = [compiled.params[name] for name in names]
    rows = await driver.fetch("EXPLAIN (ANALYZE, BUFFERS) " + compiled.string, *args)
    return "\n".join(row[0] for row in rows)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--state", default="todo")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--label", required=True)
    args = parser.parse_args()

    statement = issue_list_select(
        project_id=args.project_id,
        state=args.state,
        assignee_id=None,
        label_id=None,
        sort="created_at",
        cursor=None,
        limit=args.limit + 1,
    )
    parts = [
        f"label: {args.label}",
        f"captured_at: {datetime.now(UTC).isoformat()}",
        f"project_id: {args.project_id}",
        f"state: {args.state}",
        f"request_limit: {args.limit}",
        f"sql_limit: {args.limit + 1}",
        "statement: first page of GET /api/v1/issues?sort=created_at",
        "",
    ]
    async with SessionLocal() as session:
        connection = await session.connection()
        compiled = statement.compile(dialect=connection.dialect)
        parts.append("sql:")
        parts.append(compiled.string)
        parts.append("params:")
        for name in compiled.positiontup or ():
            parts.append(f"  {name} = {compiled.params[name]!r}")
        parts.append("")
        indexes = await session.execute(
            text(
                "SELECT indexname, indexdef FROM pg_indexes "
                "WHERE tablename = 'issues' ORDER BY indexname"
            )
        )
        parts.append("indexes:")
        for name, definition in indexes:
            parts.append(f"  {name}: {definition}")
        parts.append("")
        for run in range(1, args.runs + 1):
            # A prior execution warms the buffer cache; every plan below is kept.
            if run == 1:
                await session.execute(statement)
            plan = await _plan(connection, statement)
            parts.append(f"--- run {run} ---")
            parts.append(plan)
            parts.append("")
        await session.rollback()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(parts) + "\n")
    print(f"wrote {args.out}")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

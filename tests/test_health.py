from httpx import AsyncClient
from sqlalchemy import text

from app.db import engine


async def test_health_and_ready(client: AsyncClient) -> None:
    health = await client.get("/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}

    ready = await client.get("/ready")
    assert ready.status_code == 200
    assert ready.json()["checks"] == {"postgres": "ok", "redis": "ok"}


async def test_list_index_is_migrated() -> None:
    async with engine.connect() as connection:
        name = await connection.scalar(
            text(
                "SELECT indexname FROM pg_indexes "
                "WHERE indexname = 'ix_issues_project_state_created_id'"
            )
        )
    assert name == "ix_issues_project_state_created_id"

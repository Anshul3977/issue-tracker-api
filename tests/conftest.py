"""Fixtures against the Compose Postgres and Redis databases."""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

os.environ["DATABASE_URL"] = "postgresql+asyncpg://issue:issue@localhost:5432/issue_tracker_test"
os.environ["REDIS_URL"] = "redis://localhost:6379/1"
os.environ["BOOTSTRAP_TOKEN"] = "test-bootstrap-token"
os.environ["APP_ENV"] = "test"
os.environ["LOG_LEVEL"] = "warning"
os.environ["API_KEY_PEPPER"] = ""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.cache import get_redis
from app.db import engine
from app.main import app

ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = {"X-Bootstrap-Token": "test-bootstrap-token"}


@dataclass
class World:
    client: AsyncClient
    headers: dict[str, str]
    api_key: str
    user_id: int
    workspace_id: int
    project_id: int


@pytest.fixture(scope="session", autouse=True)
def _migrate() -> None:
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        check=True,
        cwd=ROOT,
    )


@pytest.fixture(autouse=True)
async def _clean() -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "TRUNCATE comments, issue_labels, issues, labels, projects, "
                "memberships, workspaces, users RESTART IDENTITY CASCADE"
            )
        )
    await get_redis().flushdb()


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as http:
        yield http


@pytest.fixture
async def world(client: AsyncClient) -> World:
    registered = await client.post(
        "/api/v1/auth/register",
        headers=BOOTSTRAP,
        json={"email": "ada@example.com", "name": "Ada"},
    )
    assert registered.status_code == 201, registered.text
    body = registered.json()
    headers = {"X-API-Key": body["api_key"]}
    workspace = await client.post(
        "/api/v1/workspaces",
        headers=headers,
        json={"name": "Lab", "slug": "lab"},
    )
    assert workspace.status_code == 201, workspace.text
    project = await client.post(
        "/api/v1/projects",
        headers=headers,
        json={
            "workspace_id": workspace.json()["id"],
            "name": "Core",
            "key": "CORE",
            "description": "Test project",
        },
    )
    assert project.status_code == 201, project.text
    return World(
        client=client,
        headers=headers,
        api_key=body["api_key"],
        user_id=body["user"]["id"],
        workspace_id=workspace.json()["id"],
        project_id=project.json()["id"],
    )

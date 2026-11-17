"""Liveness and readiness."""

from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.cache import get_redis
from app.db import engine

router = APIRouter(tags=["health"])
logger = logging.getLogger(__name__)


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def ready() -> JSONResponse:
    checks: dict[str, str] = {}
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception:
        logger.exception("postgres readiness check failed")
        checks["postgres"] = "error"
    try:
        pong = await get_redis().ping()
        checks["redis"] = "ok" if pong else "error"
    except Exception:
        logger.exception("redis readiness check failed")
        checks["redis"] = "error"
    status_code = 200 if all(value == "ok" for value in checks.values()) else 503
    body = {"status": "ok" if status_code == 200 else "unavailable", "checks": checks}
    return JSONResponse(status_code=status_code, content=body)

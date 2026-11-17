"""Redis cache for a single issue and a project's issue counts."""

from __future__ import annotations

import logging

from redis.asyncio import Redis

from app.config import get_settings

logger = logging.getLogger(__name__)

_client: Redis | None = None


def get_redis() -> Redis:
    global _client
    if _client is None:
        _client = Redis.from_url(get_settings().redis_url, decode_responses=True)
    return _client


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def issue_cache_key(issue_id: int) -> str:
    return f"issue:{issue_id}"


def counts_cache_key(project_id: int) -> str:
    return f"project:{project_id}:issue_counts"


async def cache_get(key: str) -> str | None:
    value = await get_redis().get(key)
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode()
    return str(value)


async def cache_set(key: str, value: str) -> None:
    await get_redis().set(key, value, ex=get_settings().cache_ttl_seconds)


async def cache_delete(*keys: str) -> None:
    if not keys:
        return
    try:
        await get_redis().delete(*keys)
    except Exception:
        logger.exception("cache delete failed for keys %s", keys)


async def invalidate_issue_write(project_id: int, issue_id: int | None) -> None:
    keys = [counts_cache_key(project_id)]
    if issue_id is not None:
        keys.append(issue_cache_key(issue_id))
    await cache_delete(*keys)

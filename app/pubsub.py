"""Redis pub/sub fanout for project events.

Each worker process holds its own subscriber and a map of local WebSockets.
Writers only publish. A socket on any worker receives the event because every
worker is subscribed to ``project:*:events``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from redis.asyncio import Redis
from starlette.websockets import WebSocket

from app.cache import get_redis
from app.config import get_settings

logger = logging.getLogger(__name__)


def dump_event(event_type: str, project_id: int, data: dict[str, Any]) -> str:
    payload = {
        "type": event_type,
        "project_id": project_id,
        "occurred_at": datetime.now(UTC).isoformat(),
        "data": data,
    }
    return json.dumps(payload, separators=(",", ":"))


class EventBus:
    def __init__(self) -> None:
        self._redis: Redis | None = None
        self._pubsub: Any = None
        self._task: asyncio.Task[None] | None = None
        self._subscribers: dict[int, set[WebSocket]] = defaultdict(set)

    async def start(self) -> None:
        if self._task is not None:
            return
        self._redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
        self._pubsub = self._redis.pubsub()
        await self._pubsub.psubscribe("project:*:events")
        self._task = asyncio.create_task(self._listen(), name="project-events")
        logger.info("subscribed to project:*:events")

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        if self._pubsub is not None:
            await self._pubsub.aclose()
            self._pubsub = None
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None
        self._subscribers.clear()

    def attach(self, project_id: int, websocket: WebSocket) -> None:
        self._subscribers[project_id].add(websocket)

    def detach(self, project_id: int, websocket: WebSocket) -> None:
        self._subscribers[project_id].discard(websocket)
        if not self._subscribers[project_id]:
            self._subscribers.pop(project_id, None)

    async def publish(self, project_id: int, payload: str) -> None:
        try:
            await get_redis().publish(f"project:{project_id}:events", payload)
        except Exception:
            logger.exception("event publish failed for project %s", project_id)

    async def _listen(self) -> None:
        assert self._pubsub is not None
        try:
            async for message in self._pubsub.listen():
                if not message or message.get("type") != "pmessage":
                    continue
                await self._dispatch(message)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("pubsub listener stopped")

    async def _dispatch(self, message: dict[str, Any]) -> None:
        channel = message.get("channel")
        data = message.get("data")
        if isinstance(channel, bytes):
            channel = channel.decode()
        if isinstance(data, bytes):
            data = data.decode()
        if not isinstance(channel, str) or not isinstance(data, str):
            return
        parts = channel.split(":")
        if len(parts) != 3 or parts[0] != "project" or parts[2] != "events":
            return
        try:
            project_id = int(parts[1])
        except ValueError:
            return
        dead: list[WebSocket] = []
        for websocket in list(self._subscribers.get(project_id, ())):
            try:
                await websocket.send_text(data)
            except Exception:
                logger.exception("websocket send failed")
                dead.append(websocket)
        for websocket in dead:
            self.detach(project_id, websocket)


bus = EventBus()

"""Project event WebSocket. Auth is a header or the ``api_key`` query param."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query, WebSocket
from sqlalchemy import select
from starlette.websockets import WebSocketDisconnect

from app.auth import hash_api_key
from app.db import SessionLocal
from app.deps import require_project
from app.errors import APIError, error_body
from app.models import User
from app.pubsub import bus, dump_event

router = APIRouter(tags=["events"])
logger = logging.getLogger(__name__)


@router.websocket("/ws/projects/{project_id}")
async def project_events(
    websocket: WebSocket,
    project_id: int,
    api_key: str | None = Query(default=None),
) -> None:
    await websocket.accept()
    token = api_key or websocket.headers.get("x-api-key")
    async with SessionLocal() as session:
        try:
            if not token:
                await websocket.send_json(error_body("unauthorized", "Missing API key"))
                await websocket.close(code=4401)
                return
            user = await session.scalar(
                select(User).where(User.api_key_hash == hash_api_key(token))
            )
            if user is None:
                await websocket.send_json(error_body("unauthorized", "Invalid API key"))
                await websocket.close(code=4401)
                return
            try:
                await require_project(session, user, project_id)
            except APIError as exc:
                await websocket.send_json(error_body(exc.code, exc.message))
                await websocket.close(code=4404)
                return
            await session.commit()
        except Exception:
            logger.exception("websocket setup failed")
            await session.rollback()
            await websocket.close(code=1011)
            return
    bus.attach(project_id, websocket)
    try:
        while True:
            message = await websocket.receive_text()
            if message == "ping":
                await websocket.send_text(dump_event("pong", project_id, {}))
    except WebSocketDisconnect:
        return
    finally:
        bus.detach(project_id, websocket)

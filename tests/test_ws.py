"""Cross-process fanout: the HTTP writer and the socket are different processes."""

from __future__ import annotations

import asyncio
import json
import os
import socket
import sys
from pathlib import Path
from urllib.parse import quote

import httpx
import websockets
from redis.asyncio import Redis

from tests.conftest import ROOT, World


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


async def _recv_type(ws: websockets.ClientConnection, event_type: str, timeout: float) -> dict:
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise TimeoutError(event_type)
        raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
        event = json.loads(raw)
        if event.get("type") == event_type:
            return event


async def test_websocket_receives_issue_and_comment_events(world: World) -> None:
    port = _free_port()
    log_path = Path(f"/tmp/issue-tracker-ws-test-{port}.log")
    log_file = log_path.open("w")
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
        stdout=log_file,
        stderr=asyncio.subprocess.STDOUT,
    )
    probe = Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    try:
        await _wait_until_ready(process, log_path, port)
        url = f"ws://127.0.0.1:{port}/ws/projects/{world.project_id}?api_key={quote(world.api_key)}"
        async with websockets.connect(url) as ws:
            await _wait_until_subscribed(probe, ws, world.project_id)
            created = await world.client.post(
                "/api/v1/issues",
                headers=world.headers,
                json={"project_id": world.project_id, "title": "Live", "state": "todo"},
            )
            assert created.status_code == 201, created.text
            issue_event = await _recv_type(ws, "issue.created", 5)
            assert issue_event["project_id"] == world.project_id
            assert issue_event["data"]["id"] == created.json()["id"]
            assert issue_event["data"]["title"] == "Live"

            comment = await world.client.post(
                f"/api/v1/issues/{created.json()['id']}/comments",
                headers=world.headers,
                json={"body": "Seen from the other process"},
            )
            assert comment.status_code == 201, comment.text
            comment_event = await _recv_type(ws, "comment.created", 5)
            assert comment_event["data"]["body"] == "Seen from the other process"
    finally:
        await probe.aclose()
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except TimeoutError:
            process.kill()
            await process.wait()
        log_file.close()


async def _wait_until_subscribed(
    probe: Redis, ws: websockets.ClientConnection, project_id: int
) -> None:
    """Publish until the other process proves it is reading the channel."""

    async def poke() -> None:
        payload = json.dumps({"type": "probe", "project_id": project_id})
        for _ in range(20):
            await probe.publish(f"project:{project_id}:events", payload)
            await asyncio.sleep(0.25)

    task = asyncio.create_task(poke())
    try:
        await _recv_type(ws, "probe", 5)
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


async def _wait_until_ready(process: asyncio.subprocess.Process, log_path: Path, port: int) -> None:
    async with httpx.AsyncClient() as client:
        for _ in range(40):
            if process.returncode is not None:
                break
            try:
                response = await client.get(f"http://127.0.0.1:{port}/ready")
                if response.status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.25)
    detail = log_path.read_text() if log_path.exists() else "websocket server did not start"
    raise RuntimeError(detail)

"""ASGI application."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response

from app import __version__
from app.cache import close_redis
from app.config import get_settings
from app.db import engine
from app.errors import APIError, error_body
from app.pubsub import bus
from app.routers import auth, comments, health, issues, projects, workspaces, ws

STATIC_DIR = Path(__file__).resolve().parent / "static"
logger = logging.getLogger(__name__)


def configure_logging() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format=(
            '{"time":"%(asctime)s","level":"%(levelname)s",'
            '"name":"%(name)s","message":"%(message)s"}'
        ),
    )


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    await bus.start()
    try:
        yield
    finally:
        await bus.stop()
        await close_redis()
        await engine.dispose()


def create_app() -> FastAPI:
    configure_logging()
    settings = get_settings()
    app = FastAPI(
        title="Issue Tracker API",
        version=__version__,
        description=(
            "Async issue tracker: workspaces, projects, issues, comments, "
            "keyset pagination, a Redis cache, and live project events."
        ),
        lifespan=lifespan,
    )
    if settings.cors_origins.strip():
        origins = [item.strip() for item in settings.cors_origins.split(",") if item.strip()]
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.exception_handler(APIError)
    async def api_error(_request: Request, exc: APIError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(exc.code, exc.message, exc.details),
        )

    @app.exception_handler(HTTPException)
    async def http_error(_request: Request, exc: HTTPException) -> JSONResponse:
        codes = {401: "unauthorized", 403: "forbidden", 404: "not_found", 409: "conflict"}
        message = exc.detail if isinstance(exc.detail, str) else "Request failed"
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(codes.get(exc.status_code, "http_error"), message),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        details: list[dict[str, Any]] = []
        for err in exc.errors():
            details.append(
                {
                    "loc": [str(item) for item in err.get("loc", ())],
                    "msg": str(err.get("msg", "")),
                    "type": str(err.get("type", "")),
                }
            )
        return JSONResponse(
            status_code=422,
            content=error_body("validation_error", "Request validation failed", details),
        )

    @app.exception_handler(Exception)
    async def unhandled(_request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error", exc_info=exc)
        return JSONResponse(
            status_code=500,
            content=error_body("internal_error", "Internal server error"),
        )

    versioned = APIRouter(prefix="/api/v1")
    versioned.include_router(auth.router)
    versioned.include_router(workspaces.router)
    versioned.include_router(projects.router)
    versioned.include_router(issues.router)
    versioned.include_router(comments.router)
    app.include_router(health.router)
    app.include_router(versioned)
    app.include_router(ws.router)

    @app.get("/", include_in_schema=False)
    async def demo_page() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon() -> Response:
        return Response(status_code=204)

    return app


app = create_app()

"""Runtime settings loaded from the environment."""

from __future__ import annotations

from functools import lru_cache
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def normalize_database_url(url: str) -> tuple[str, dict[str, Any]]:
    """Return an asyncpg SQLAlchemy URL and connect args.

    Render hands out ``postgres://`` URLs and puts ``sslmode`` in the query
    string. asyncpg does not understand ``sslmode``, so that flag is moved
    onto the driver's ``ssl`` connect argument.
    """

    raw = url.strip()
    if raw.startswith("postgres://"):
        raw = "postgresql://" + raw[len("postgres://") :]
    if raw.startswith("postgresql://"):
        raw = "postgresql+asyncpg://" + raw[len("postgresql://") :]
    if not raw.startswith("postgresql+asyncpg://"):
        raise ValueError("DATABASE_URL must be a PostgreSQL URL")

    parts = urlsplit(raw)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    sslmode = query.pop("sslmode", None)
    query.pop("channel_binding", None)
    connect_args: dict[str, Any] = {}
    if sslmode in {"require", "verify-ca", "verify-full"}:
        connect_args["ssl"] = "require"
    normalized = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))
    return normalized, connect_args


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    redis_url: str = "redis://localhost:6379/0"
    app_env: str = "local"
    log_level: str = "info"
    bootstrap_token: str | None = None
    api_key_pepper: str = ""
    cors_origins: str = ""
    db_pool_size: int = 5
    db_max_overflow: int = 5
    db_pool_timeout: int = 30
    cache_ttl_seconds: int = Field(default=60, ge=1)
    port: int = 8000

    @property
    def async_database_url(self) -> str:
        return normalize_database_url(self.database_url)[0]

    @property
    def database_connect_args(self) -> dict[str, Any]:
        return normalize_database_url(self.database_url)[1]


@lru_cache
def get_settings() -> Settings:
    # DATABASE_URL is required at runtime and loaded from the environment.
    return Settings()  # type: ignore[call-arg]

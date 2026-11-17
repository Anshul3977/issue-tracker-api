"""Bootstrap registration and the current user."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import bootstrap_matches, generate_api_key, hash_api_key
from app.db import get_session
from app.deps import get_current_user
from app.errors import APIError
from app.models import User
from app.present import user_out
from app.schemas import RegisterIn, RegisterOut, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=RegisterOut, status_code=201)
async def register(
    body: RegisterIn,
    session: AsyncSession = Depends(get_session),
    bootstrap_token: str | None = Header(default=None, alias="X-Bootstrap-Token"),
) -> RegisterOut:
    if not bootstrap_matches(bootstrap_token):
        raise APIError(401, "unauthorized", "Invalid bootstrap token")
    existing = await session.scalar(select(User.id).where(User.email == body.email))
    if existing is not None:
        raise APIError(409, "conflict", "Email is already registered")
    api_key = generate_api_key()
    user = User(
        email=body.email,
        name=body.name,
        api_key_hash=hash_api_key(api_key),
        created_at=datetime.now(UTC),
    )
    session.add(user)
    await session.flush()
    return RegisterOut(user=user_out(user), api_key=api_key)


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)) -> UserOut:
    return user_out(user)

"""API key hashing. Keys are random and stored as SHA-256 digests."""

from __future__ import annotations

import hashlib
import secrets

from app.config import get_settings


def hash_api_key(api_key: str) -> str:
    pepper = get_settings().api_key_pepper.encode()
    return hashlib.sha256(pepper + b"\0" + api_key.encode()).hexdigest()


def generate_api_key() -> str:
    return secrets.token_urlsafe(32)


def bootstrap_matches(provided: str | None) -> bool:
    expected = get_settings().bootstrap_token
    if not expected or not provided:
        return False
    return secrets.compare_digest(provided, expected)

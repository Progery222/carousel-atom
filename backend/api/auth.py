"""API key authentication for the public /api/v1 router.

Keys are read from the `CAROUSEL_API_KEYS` env var (comma-separated).
Optional `name:key` form lets you label each key for logs and rate-limit
buckets — e.g. `CAROUSEL_API_KEYS=internal:abc123,partner_acme:xyz789`.
A bare key gets the auto name `key1`, `key2`, etc.
"""
from __future__ import annotations

import hmac
import os
from dataclasses import dataclass

from fastapi import Header, HTTPException, status


@dataclass(frozen=True)
class ApiKeyInfo:
    name: str
    key: str


def _load_keys() -> list[ApiKeyInfo]:
    raw = os.environ.get("CAROUSEL_API_KEYS", "")
    out: list[ApiKeyInfo] = []
    for i, item in enumerate(raw.split(",")):
        item = item.strip()
        if not item:
            continue
        if ":" in item:
            name, _, key = item.partition(":")
            name = name.strip()
            key = key.strip()
            if not name or not key:
                continue
        else:
            name, key = f"key{i + 1}", item
        out.append(ApiKeyInfo(name=name, key=key))
    return out


# Loaded once at import. Tests can monkeypatch this list directly.
API_KEYS: list[ApiKeyInfo] = _load_keys()


def reload_keys() -> None:
    """Reload from env. Useful in tests."""
    global API_KEYS
    API_KEYS = _load_keys()


def verify_api_key(x_api_key: str | None = Header(default=None)) -> ApiKeyInfo:
    """FastAPI dependency. Returns the matched ApiKeyInfo or raises 401/503.

    503 when no keys are configured — the public API is intentionally
    unreachable until an operator sets at least one key.
    """
    if not API_KEYS:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="public API disabled: set CAROUSEL_API_KEYS env var",
        )
    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing X-API-Key header",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    for info in API_KEYS:
        if hmac.compare_digest(info.key, x_api_key):
            return info
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="invalid API key",
        headers={"WWW-Authenticate": "ApiKey"},
    )

"""API key authentication + scopes for the public /api/v1 router.

Two key sources:
- **Env bootstrap keys** (`CAROUSEL_API_KEYS`, comma-separated, optional
  `name:key` form). These are full-access **admin** keys, used to bootstrap and
  to mint scoped keys. Compared in constant time.
- **DB-backed scoped keys** (`core.api_keys`): only a hash is stored; the raw
  secret is shown once at creation. Each carries `read`/`write`/`admin` scopes.

A single generic 401 is returned for missing / unknown / no-keys-configured so
the provisioning state isn't disclosed.
"""
from __future__ import annotations

import hmac
import os
from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, Header, HTTPException, Request, status

from core import api_keys

# Scope hierarchy: admin ⊃ write ⊃ read.
SCOPE_RANK = {"read": 1, "write": 2, "admin": 3}


@dataclass(frozen=True)
class ApiKeyInfo:
    name: str
    scopes: frozenset = frozenset()
    key_id: Optional[str] = None  # public id for DB keys (None for env keys)
    source: str = "db"            # "env" | "db"
    key: str = ""                 # raw value, only kept for env keys (compare)


def _load_env_keys() -> list[ApiKeyInfo]:
    raw = os.environ.get("CAROUSEL_API_KEYS", "")
    out: list[ApiKeyInfo] = []
    for i, item in enumerate(raw.split(",")):
        item = item.strip()
        if not item:
            continue
        if ":" in item:
            name, _, key = item.partition(":")
            name, key = name.strip(), key.strip()
            if not name or not key:
                continue
        else:
            name, key = f"key{i + 1}", item
        out.append(ApiKeyInfo(name=name, scopes=frozenset({"admin"}),
                              source="env", key=key))
    return out


# Loaded once at import. Tests can call reload_keys() after setting env.
ENV_KEYS: list[ApiKeyInfo] = _load_env_keys()


def reload_keys() -> None:
    """Reload env bootstrap keys. Useful in tests."""
    global ENV_KEYS
    ENV_KEYS = _load_env_keys()


def _unauthorized() -> HTTPException:
    # One generic message for every unauthenticated case (missing header,
    # unknown key, no keys configured) — no provisioning-state disclosure.
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="invalid or missing API key",
        headers={"WWW-Authenticate": "ApiKey"},
    )


def verify_api_key(x_api_key: Optional[str]) -> ApiKeyInfo:
    """Resolve an X-API-Key to an ApiKeyInfo or raise a uniform 401.
    Env bootstrap keys (admin scope) are checked first (constant-time), then
    DB-backed hashed keys."""
    if not x_api_key:
        raise _unauthorized()
    for info in ENV_KEYS:
        if hmac.compare_digest(info.key, x_api_key):
            return info
    rec = api_keys.verify(x_api_key)
    if rec is not None:
        return ApiKeyInfo(
            name=rec["name"],
            scopes=frozenset(rec["scopes"]),
            key_id=rec["key_id"],
            source="db",
        )
    raise _unauthorized()


def auth_dependency(request: Request,
                    x_api_key: Optional[str] = Header(default=None)) -> ApiKeyInfo:
    """Router-level dependency: authenticate and stash the key on
    `request.state.api_key` (read by the rate limiter, the access log, and async
    job attribution — all rely on the `.name` attribute)."""
    info = verify_api_key(x_api_key)
    request.state.api_key = info
    return info


def has_scope(info: ApiKeyInfo, needed: str) -> bool:
    have = max((SCOPE_RANK.get(s, 0) for s in info.scopes), default=0)
    return have >= SCOPE_RANK.get(needed, 99)


def require_scope(needed: str):
    """Per-route dependency factory enforcing a minimum scope. Depends on
    `auth_dependency` (cached per request) so it sees the authenticated key."""

    def _dep(info: ApiKeyInfo = Depends(auth_dependency)) -> ApiKeyInfo:
        if not has_scope(info, needed):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"insufficient scope: '{needed}' required",
            )
        return info

    return _dep

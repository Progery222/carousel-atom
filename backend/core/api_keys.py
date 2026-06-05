"""Database-backed, hashed API keys for the public /api/v1 surface.

Keys are high-entropy random tokens; we store only their SHA-256 hash (plus an
optional server-side pepper) and a non-secret `key_id`/`key_prefix` for listing
and revoking. The raw secret is returned exactly once, at creation, and never
stored or logged. Constant-time compare on lookup; `last_used_at` is updated
best-effort and throttled to avoid write amplification on the shared WAL DB.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from typing import Optional

from core.dedup import conn
from core.log import get_logger

log = get_logger("api.keys")

VALID_SCOPES = ("read", "write", "admin")
KEY_PREFIX = "csk_"  # carousel-studio key
_LAST_USED_THROTTLE = 60  # seconds — collapse a key's request burst into ≤1 write/min

SCHEMA = """
CREATE TABLE IF NOT EXISTS api_keys (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    key_id       TEXT NOT NULL UNIQUE,
    name         TEXT NOT NULL,
    key_prefix   TEXT NOT NULL,
    key_hash     TEXT NOT NULL UNIQUE,
    scopes       TEXT NOT NULL,
    created_at   INTEGER NOT NULL,
    last_used_at INTEGER,
    revoked_at   INTEGER
);
CREATE INDEX IF NOT EXISTS idx_api_keys_hash ON api_keys(key_hash);
"""


def init_db() -> None:
    with conn() as c:
        c.executescript(SCHEMA)


def _hash(raw: str) -> str:
    """SHA-256 of the raw key. With CAROUSEL_KEY_PEPPER set, HMAC-SHA256 so a
    read-only DB leak alone can't verify guessed keys (keys are 256-bit, so the
    pepper is optional defense-in-depth, not load-bearing)."""
    pepper = os.environ.get("CAROUSEL_KEY_PEPPER", "")
    if pepper:
        return hmac.new(pepper.encode("utf-8"), raw.encode("utf-8"),
                        hashlib.sha256).hexdigest()
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _row_to_public(row) -> dict:
    return {
        "key_id": row["key_id"],
        "name": row["name"],
        "key_prefix": row["key_prefix"],
        "scopes": json.loads(row["scopes"]),
        "created_at": row["created_at"],
        "last_used_at": row["last_used_at"],
        "revoked_at": row["revoked_at"],
    }


def create_key(name: str, scopes: list[str]) -> dict:
    """Mint a key. Returns the public record PLUS the raw secret under `key`
    (shown ONCE). Raises ValueError on an unknown scope."""
    init_db()
    bad = [s for s in scopes if s not in VALID_SCOPES]
    if bad:
        raise ValueError(f"unknown scope(s): {', '.join(bad)}")
    raw = KEY_PREFIX + secrets.token_urlsafe(32)
    key_id = secrets.token_hex(8)
    scopes_sorted = sorted(set(scopes))
    created_at = int(time.time())
    with conn() as c:
        c.execute(
            "INSERT INTO api_keys(key_id,name,key_prefix,key_hash,scopes,created_at) "
            "VALUES (?,?,?,?,?,?)",
            (key_id, name, raw[:12], _hash(raw), json.dumps(scopes_sorted), created_at),
        )
    return {
        "key_id": key_id, "name": name, "key_prefix": raw[:12],
        "scopes": scopes_sorted, "created_at": created_at,
        "last_used_at": None, "revoked_at": None, "key": raw,
    }


def verify(raw: str) -> Optional[dict]:
    """Return the public record for a valid, non-revoked key, else None.
    Lookup is by hash-of-input (indexed, timing-safe); `last_used_at` is
    updated best-effort."""
    if not raw:
        return None
    digest = _hash(raw)
    try:
        with conn() as c:
            row = c.execute(
                "SELECT * FROM api_keys WHERE key_hash=? AND revoked_at IS NULL",
                (digest,),
            ).fetchone()
    except sqlite3.OperationalError:
        # Table not created yet (e.g. before lifespan init) — no DB keys exist.
        return None
    if row is None:
        return None
    if not hmac.compare_digest(row["key_hash"], digest):  # belt-and-suspenders
        return None
    _touch(row["key_id"], row["last_used_at"])
    return _row_to_public(row)


def _touch(key_id: str, last_used_at: Optional[int]) -> None:
    now = int(time.time())
    if last_used_at is not None and now - last_used_at < _LAST_USED_THROTTLE:
        return
    try:
        with conn() as c:
            c.execute("UPDATE api_keys SET last_used_at=? WHERE key_id=?", (now, key_id))
    except Exception:
        # Never fail auth because a usage-timestamp write contended on the DB.
        log.debug("last_used_at update skipped for %s", key_id, exc_info=True)


def list_keys() -> list[dict]:
    init_db()
    with conn() as c:
        rows = c.execute("SELECT * FROM api_keys ORDER BY created_at DESC, id DESC").fetchall()
    return [_row_to_public(r) for r in rows]


def get_key(key_id: str) -> Optional[dict]:
    init_db()
    with conn() as c:
        row = c.execute("SELECT * FROM api_keys WHERE key_id=?", (key_id,)).fetchone()
    return _row_to_public(row) if row else None


def revoke_key(key_id: str) -> bool:
    init_db()
    with conn() as c:
        cur = c.execute(
            "UPDATE api_keys SET revoked_at=? WHERE key_id=? AND revoked_at IS NULL",
            (int(time.time()), key_id),
        )
        return cur.rowcount > 0

"""Standard /api/v1 response helpers: success envelope + cursor pagination.

Every /api/v1 JSON handler returns `ok(data, request)` so the wire shape is the
cross-service standard `{success, data, meta:{request_id}}`. Errors are produced
by the exception handlers in `api.server`. Pagination is keyset (cursor), never
OFFSET, so it stays stable under concurrent inserts.
"""
from __future__ import annotations

import base64
from typing import Any, Callable, Optional

from fastapi import HTTPException, Request


def ok(data: Any, request: Request) -> dict:
    """Wrap a handler's payload in the success envelope. `data` may be a model,
    list, or dict — FastAPI serializes it through the route's `response_model`
    (an `Envelope[T]`)."""
    rid = getattr(request.state, "request_id", "")
    return {"success": True, "data": data, "meta": {"request_id": rid}}


# ── cursor pagination ───────────────────────────────────────────────────────
#
# A cursor encodes the keyset position `(created_at, id)` of the last item on a
# page. It is opaque (urlsafe base64) but not a security boundary — the holder
# could already list everything. Decoding tolerates stripped padding.


def encode_cursor(created_at: int, row_id: int) -> str:
    raw = f"{int(created_at)}:{int(row_id)}".encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(cursor: Optional[str]) -> Optional[tuple[int, int]]:
    """Decode a cursor to `(created_at, id)`, or None when absent. A malformed
    cursor is a client error -> 422 validation_error (never a 500)."""
    if not cursor:
        return None
    try:
        pad = "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(cursor + pad).decode("utf-8")
        ts, rid = raw.split(":", 1)
        return int(ts), int(rid)
    except Exception:
        raise HTTPException(status_code=422, detail="invalid cursor")


def paginate_sorted(
    rows: list,
    *,
    limit: int,
    cursor: Optional[str],
    key: Callable[[Any], tuple[int, int]],
) -> tuple[list, Optional[str]]:
    """Keyset-paginate an in-memory list (e.g. async jobs).

    `rows` must already be sorted DESC by `key` -> (created_at, id). Returns the
    page plus a `next_cursor` (None when exhausted).
    """
    after = decode_cursor(cursor)
    if after is not None:
        rows = [r for r in rows if key(r) < after]  # strictly older than cursor
    page = rows[:limit]
    next_cursor = None
    if len(rows) > limit and page:
        ca, rid = key(page[-1])
        next_cursor = encode_cursor(ca, rid)
    return page, next_cursor

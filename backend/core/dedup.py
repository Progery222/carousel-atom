"""SQLite-backed deduplication and post tracking.

Replaces F1's seen_news.json. Per-topic seen-store + cross-topic post log.

Improvements over the original:
- WAL mode + busy_timeout so concurrent FastAPI workers don't deadlock.
- `prune_seen(days=N)` for manual or cron-based cleanup.
- `is_seen_anywhere(url, title)` — cross-topic duplicate check (lifestyle and
  NBA can otherwise both publish the same Bleacher Report story).
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "factory.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS seen (
    topic       TEXT NOT NULL,
    url_hash    TEXT NOT NULL,
    title_hash  TEXT NOT NULL,
    url         TEXT NOT NULL,
    title       TEXT NOT NULL,
    first_seen  INTEGER NOT NULL,
    PRIMARY KEY (topic, url_hash)
);
CREATE INDEX IF NOT EXISTS idx_seen_title ON seen(topic, title_hash);
CREATE INDEX IF NOT EXISTS idx_seen_first ON seen(first_seen);

CREATE TABLE IF NOT EXISTS posts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    topic       TEXT NOT NULL,
    run_id      TEXT NOT NULL,
    posted_at   INTEGER NOT NULL,
    platform    TEXT NOT NULL,
    external_id TEXT,
    caption     TEXT,
    slide_count INTEGER
);
CREATE INDEX IF NOT EXISTS idx_posts_topic_time ON posts(topic, posted_at);
"""


def _hash(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8", errors="ignore")).hexdigest()[:16]


def normalize_title(title: str) -> str:
    t = title.lower().strip()
    t = re.sub(r"[^a-z0-9 ]+", "", t)
    t = re.sub(r"\s+", " ", t)
    return t


@contextmanager
def conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=10.0)
    c.row_factory = sqlite3.Row
    # WAL gives much better concurrency for one-writer / many-readers.
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    c.execute("PRAGMA busy_timeout=5000")
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init_db() -> None:
    with conn() as c:
        c.executescript(SCHEMA)


@dataclass
class SeenRecord:
    topic: str
    url: str
    title: str


def is_seen(topic: str, url: str, title: str) -> bool:
    """True if this URL OR a near-identical title was already seen for this topic."""
    uh = _hash(url)
    th = _hash(normalize_title(title))
    with conn() as c:
        row = c.execute(
            "SELECT 1 FROM seen WHERE topic=? AND (url_hash=? OR title_hash=?) LIMIT 1",
            (topic, uh, th),
        ).fetchone()
        return row is not None


def is_seen_anywhere(url: str, title: str) -> bool:
    """Cross-topic dup check: same URL/title published under any topic."""
    uh = _hash(url)
    th = _hash(normalize_title(title))
    with conn() as c:
        row = c.execute(
            "SELECT 1 FROM seen WHERE url_hash=? OR title_hash=? LIMIT 1",
            (uh, th),
        ).fetchone()
        return row is not None


def mark_seen(records: list[SeenRecord]) -> None:
    if not records:
        return
    now = int(time.time())
    with conn() as c:
        c.executemany(
            "INSERT OR IGNORE INTO seen(topic, url_hash, title_hash, url, title, first_seen) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                (r.topic, _hash(r.url), _hash(normalize_title(r.title)), r.url, r.title, now)
                for r in records
            ],
        )


def log_post(topic: str, run_id: str, platform: str, caption: str,
             slide_count: int, external_id: str | None = None) -> None:
    with conn() as c:
        c.execute(
            "INSERT INTO posts(topic, run_id, posted_at, platform, external_id, caption, slide_count) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (topic, run_id, int(time.time()), platform, external_id, caption, slide_count),
        )


def reset_topic(topic: str) -> int:
    with conn() as c:
        cur = c.execute("DELETE FROM seen WHERE topic=?", (topic,))
        return cur.rowcount


def prune_seen(days: int = 90) -> int:
    """Drop seen rows older than N days. Run on a cron / Studio settings."""
    cutoff = int(time.time()) - days * 86400
    with conn() as c:
        cur = c.execute("DELETE FROM seen WHERE first_seen < ?", (cutoff,))
        return cur.rowcount


def stats(topic: str) -> dict:
    with conn() as c:
        seen_count = c.execute(
            "SELECT COUNT(*) FROM seen WHERE topic=?", (topic,)
        ).fetchone()[0]
        post_count = c.execute(
            "SELECT COUNT(*) FROM posts WHERE topic=?", (topic,)
        ).fetchone()[0]
        last_post = c.execute(
            "SELECT MAX(posted_at) FROM posts WHERE topic=?", (topic,)
        ).fetchone()[0]
    return {"seen": seen_count, "posts": post_count, "last_post": last_post}


def recent_posts(limit: int = 30) -> list[dict]:
    """Most recent posted runs across all topics — used by the studio history."""
    with conn() as c:
        rows = c.execute(
            "SELECT topic, run_id, posted_at, platform, slide_count, caption "
            "FROM posts ORDER BY posted_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]

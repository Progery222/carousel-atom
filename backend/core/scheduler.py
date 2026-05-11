"""Cron-style trigger that respects each topic's `schedule.send_hours`.

The studio doesn't run a daemon — we lean on the OS cron / launchd /
systemd timer to hit `POST /schedule/trigger` on a fixed cadence. This
helper decides which topics are "due" right now and runs them.

Usage from the API:

    from core.scheduler import run_due_topics
    result = run_due_topics(design="newsflash", deliver="telegram")

`now` can be overridden for tests.
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable

from core.log import get_logger
from core.pipeline import run_once
from core.topic_loader import list_topics, load_topic, TopicConfig

log = get_logger("scheduler")

try:  # stdlib zoneinfo (3.9+); pytz is optional fallback
    from zoneinfo import ZoneInfo as _ZoneInfo
    _zone = lambda tz: _ZoneInfo(tz)  # noqa: E731
except Exception:  # pragma: no cover
    import pytz
    _zone = lambda tz: pytz.timezone(tz)  # noqa: E731


def _topic_is_due(topic: TopicConfig, now: datetime, *, window_min: int = 30) -> bool:
    """A topic is "due" if `now` falls within `window_min` minutes of any
    of its `schedule.send_hours` entries (in the topic's local timezone).
    """
    try:
        local = now.astimezone(_zone(topic.schedule.timezone or "UTC"))
    except Exception:
        local = now
    cur_minutes = local.hour * 60 + local.minute
    for h in topic.schedule.send_hours or []:
        target = int(h) * 60
        if abs(cur_minutes - target) <= window_min:
            return True
    return False


def due_topics(now: datetime | None = None,
               *, window_min: int = 30,
               only: Iterable[str] | None = None) -> list[str]:
    now = now or datetime.now(tz=_zone("UTC"))
    pool = list(only) if only else list_topics()
    return [
        slug for slug in pool
        if _topic_is_due(load_topic(slug), now, window_min=window_min)
    ]


def run_due_topics(*, design: str = "newsflash", deliver: str = "",
                   window_min: int = 30, dry_run: bool = False) -> dict:
    """Render every topic whose schedule says it's due. Returns a per-topic
    summary so a cron caller can log or alert on failures.
    """
    slugs = due_topics(window_min=window_min)
    runs: list[dict] = []
    for slug in slugs:
        if dry_run:
            runs.append({"topic": slug, "status": "dry_run"})
            continue
        try:
            r = run_once(slug, design, deliver=deliver)
            runs.append({
                "topic": slug,
                "status": r.get("status"),
                "run_id": r.get("run_id"),
                "delivery": r.get("delivery"),
            })
        except Exception as e:
            log.warning("scheduled run for %s failed: %s", slug, e)
            runs.append({"topic": slug, "status": "error", "error": str(e)})
    return {"due": slugs, "runs": runs}

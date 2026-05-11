"""Scheduler tests — verify the due-window logic without rendering anything."""
from datetime import datetime
from unittest.mock import patch

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    import pytz
    ZoneInfo = pytz.timezone  # type: ignore

from core import scheduler
from core.topic_loader import (
    Brand, CarouselConfig, CaptionConfig, CTA, Schedule, Source, TopicConfig,
)


def _topic(send_hours, tz="UTC"):
    return TopicConfig(
        slug="test", display_name="Test Daily", language="en",
        sources=[Source(kind="rss", name="x", feed="x")],
        brand=Brand(bg=(0,0,0), accent=(255,0,0), accent_light=(255,100,100)),
        cta=CTA(headline="x"),
        caption=CaptionConfig(intro="x", hashtags=[]),
        carousel=CarouselConfig(),
        schedule=Schedule(timezone=tz, send_hours=send_hours),
    )


def test_due_within_window():
    t = _topic([9, 15, 21])
    now = datetime(2026, 4, 29, 9, 10, tzinfo=ZoneInfo("UTC"))
    assert scheduler._topic_is_due(t, now, window_min=30)


def test_not_due_outside_window():
    t = _topic([9, 15, 21])
    now = datetime(2026, 4, 29, 12, 0, tzinfo=ZoneInfo("UTC"))
    assert not scheduler._topic_is_due(t, now, window_min=30)


def test_timezone_respected():
    # 09:00 Europe/Berlin == 07:00 UTC
    t = _topic([9], tz="Europe/Berlin")
    now = datetime(2026, 4, 29, 7, 5, tzinfo=ZoneInfo("UTC"))
    assert scheduler._topic_is_due(t, now, window_min=30)


def test_due_topics_filters_global_list(monkeypatch):
    t = _topic([9])
    monkeypatch.setattr(scheduler, "list_topics", lambda: ["test"])
    monkeypatch.setattr(scheduler, "load_topic", lambda slug: t)
    now = datetime(2026, 4, 29, 9, 0, tzinfo=ZoneInfo("UTC"))
    assert scheduler.due_topics(now=now) == ["test"]
    now_off = datetime(2026, 4, 29, 13, 0, tzinfo=ZoneInfo("UTC"))
    assert scheduler.due_topics(now=now_off) == []


def test_dry_run_returns_status_without_calling_pipeline(monkeypatch):
    t = _topic([9])
    monkeypatch.setattr(scheduler, "list_topics", lambda: ["test"])
    monkeypatch.setattr(scheduler, "load_topic", lambda slug: t)
    with patch("core.scheduler.run_once") as run_once:
        # Force the scheduler to think *now* is 09:05 UTC.
        with patch("core.scheduler.due_topics", return_value=["test"]):
            res = scheduler.run_due_topics(dry_run=True)
    assert res["due"] == ["test"]
    assert res["runs"][0]["status"] == "dry_run"
    assert run_once.called is False

"""Generic RSS parser. Works for ESPN, BBC Sport, Goal, NHL, MLB, TechCrunch, etc."""
from __future__ import annotations

from email.utils import parsedate_to_datetime

import feedparser

from core.log import get_logger
from core.parsers.base import Article

log = get_logger("parser.rss")


def _ts(entry) -> int | None:
    for key in ("published", "updated"):
        v = entry.get(key)
        if not v:
            continue
        try:
            return int(parsedate_to_datetime(v).timestamp())
        except Exception:
            pass
    return None


def _image_from_entry(entry) -> str:
    # media:content / media:thumbnail / enclosures / first <img> in summary
    if entry.get("media_content"):
        for m in entry.media_content:
            if m.get("url"):
                return m["url"]
    if entry.get("media_thumbnail"):
        for m in entry.media_thumbnail:
            if m.get("url"):
                return m["url"]
    for enc in entry.get("enclosures", []) or []:
        if enc.get("type", "").startswith("image"):
            return enc.get("url", "") or enc.get("href", "")
    summary = entry.get("summary", "")
    if "<img" in summary:
        import re
        m = re.search(r'<img[^>]+src="([^"]+)"', summary)
        if m:
            return m.group(1)
    return ""


def fetch_rss(feed_url: str, source_name: str, limit: int = 25) -> list[Article]:
    parsed = feedparser.parse(feed_url, request_headers={"User-Agent": "Mozilla/5.0"})
    if parsed.bozo and not parsed.entries:
        log.warning("%s parse error: %s", source_name, parsed.bozo_exception)
        return []

    out: list[Article] = []
    for e in parsed.entries[:limit]:
        title = (e.get("title") or "").strip()
        link = (e.get("link") or "").strip()
        if not title or not link:
            continue
        out.append(Article(
            title=title,
            url=link,
            source=source_name,
            image_url=_image_from_entry(e),
            # 2000 chars instead of 500: feeds wrap real summaries in
            # <div>/<img>/<a> blocks that eat 200-400 chars before the
            # actual prose. clean_description() strips that markup later;
            # we just need enough raw material to survive the strip.
            description=(e.get("summary") or "").strip()[:2000],
            published_ts=_ts(e),
        ))
    log.info("%s: %d articles", source_name, len(out))
    return out

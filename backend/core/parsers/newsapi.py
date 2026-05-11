"""NewsAPI.org parser — closes the gap that `Source.kind = 'newsapi'` was
declared but never implemented.

Source YAML:

    - kind: newsapi
      name: NewsAPI · F1
      query: "formula 1 OR f1"
      domains: ""              # optional, comma-separated whitelist
      language: en             # optional, 2-letter code
      sort_by: publishedAt     # publishedAt | relevancy | popularity

API key is taken from `NEWSAPI_KEY` env var. If missing, the parser logs
once and returns an empty list rather than crashing the whole pipeline.
"""
from __future__ import annotations

import os
import threading
import time
from email.utils import parsedate_to_datetime

from core import http as http_client
from core.log import get_logger
from core.parsers.base import Article

log = get_logger("parser.newsapi")

API = "https://newsapi.org/v2/everything"
# `fetch_newsapi` is called concurrently from `pipeline._collect`'s
# ThreadPoolExecutor — without a lock, every worker that hits the no-key
# branch races to flip the flag and we log the same warning N times.
_warned_no_key = False
_warned_lock = threading.Lock()


def _ts(iso: str | None) -> int | None:
    if not iso:
        return None
    try:
        # NewsAPI uses ISO-8601 with Z suffix
        from datetime import datetime
        return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())
    except Exception:
        try:
            return int(parsedate_to_datetime(iso).timestamp())
        except Exception:
            return None


def fetch_newsapi(
    query: str,
    source_name: str,
    *,
    domains: str = "",
    language: str = "en",
    sort_by: str = "publishedAt",
    page_size: int = 25,
) -> list[Article]:
    """Pull `everything` for the given query and convert to Article rows."""
    global _warned_no_key
    api_key = os.environ.get("NEWSAPI_KEY")
    if not api_key:
        with _warned_lock:
            if not _warned_no_key:
                log.warning("NEWSAPI_KEY not set — newsapi sources are skipped")
                _warned_no_key = True
        return []

    params = {
        "q": query,
        "language": language,
        "sortBy": sort_by,
        "pageSize": min(page_size, 100),
        # Default to the last 7 days so the freshness gate filters to today.
        "from": time.strftime("%Y-%m-%d", time.gmtime(time.time() - 7 * 86400)),
    }
    if domains:
        params["domains"] = domains

    try:
        resp = http_client.get(
            API,
            params=params,
            headers={"X-Api-Key": api_key},
            timeout=20,
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception as e:
        log.warning("%s fetch failed: %s", source_name, e)
        return []

    if payload.get("status") != "ok":
        log.warning("%s NewsAPI error: %s", source_name, payload)
        return []

    out: list[Article] = []
    for entry in payload.get("articles") or []:
        title = (entry.get("title") or "").strip()
        url = (entry.get("url") or "").strip()
        if not title or not url or title == "[Removed]":
            continue
        out.append(Article(
            title=title,
            url=url,
            source=source_name,
            image_url=(entry.get("urlToImage") or "").strip(),
            description=(entry.get("description") or "").strip()[:500],
            published_ts=_ts(entry.get("publishedAt")),
        ))
    log.info("%s: %d articles", source_name, len(out))
    return out

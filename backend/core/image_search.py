"""Fallback image search.

Pipeline calls `find_replacement_image(article)` when an article either
arrives without an image or with one that's too small/blurry. We try
each adapter in priority order and return the first usable URL.

Adapters:
  1. Wikimedia Commons — no API key, encyclopaedic photos. Great for
     athletes, teams, stadiums, brand items (Panini sticker album).
  2. Pexels        — needs `PEXELS_API_KEY`, broad stock photo coverage.
  3. Unsplash      — needs `UNSPLASH_ACCESS_KEY`, similar.

All three are wrapped in try/except so a flaky API can never crash the
render. Each returns `None` when nothing usable is found.
"""
from __future__ import annotations

import os
from typing import Iterable

from core import http as http_client
from core.log import get_logger
from core.text import extract_entities

log = get_logger("image_search")

WIKIMEDIA_API = "https://commons.wikimedia.org/w/api.php"
PEXELS_API = "https://api.pexels.com/v1/search"
UNSPLASH_API = "https://api.unsplash.com/search/photos"

MIN_RESULT_WIDTH = 800   # only accept candidates at least this wide


# ── Wikimedia ──────────────────────────────────────────────────────────────


def search_wikimedia(query: str) -> str | None:
    """Search Wikimedia Commons via the MediaWiki API.

    Returns a thumbnail URL clamped to ~1600 px wide if a hit is found.
    """
    if not query.strip():
        return None
    try:
        # Step 1: search the File: namespace
        resp = http_client.get(
            WIKIMEDIA_API,
            params={
                "action": "query",
                "format": "json",
                "list": "search",
                "srsearch": f"{query} filemime:image/jpeg|image/png",
                "srnamespace": 6,  # File: namespace
                "srlimit": 5,
            },
            timeout=10,
        )
        resp.raise_for_status()
        results = resp.json().get("query", {}).get("search", []) or []
        if not results:
            return None
        # Step 2: walk hits in order, fetch imageinfo, pick first usable
        titles = [r["title"] for r in results]
        info = http_client.get(
            WIKIMEDIA_API,
            params={
                "action": "query",
                "format": "json",
                "titles": "|".join(titles),
                "prop": "imageinfo",
                "iiprop": "url|size",
                "iiurlwidth": 1600,
            },
            timeout=10,
        ).json()
        pages = info.get("query", {}).get("pages", {}) or {}
        # Pages dict is keyed by Wikimedia internal IDs. We scan ALL pages
        # and pick the first that meets MIN_RESULT_WIDTH.
        for page in pages.values():
            for ii in page.get("imageinfo", []) or []:
                url = ii.get("thumburl") or ii.get("url")
                width = ii.get("thumbwidth") or ii.get("width", 0)
                if url and width >= MIN_RESULT_WIDTH:
                    return url
        return None
    except Exception as e:
        log.warning("wikimedia search failed for %r: %s", query, e)
        return None


# ── Pexels ─────────────────────────────────────────────────────────────────


def search_pexels(query: str) -> str | None:
    key = os.environ.get("PEXELS_API_KEY")
    if not key or not query.strip():
        return None
    try:
        resp = http_client.get(
            PEXELS_API,
            params={"query": query, "per_page": 3, "size": "large",
                    "orientation": "landscape"},
            headers={"Authorization": key},
            timeout=10,
        )
        resp.raise_for_status()
        for p in resp.json().get("photos", []) or []:
            src = p.get("src", {}) or {}
            url = src.get("large2x") or src.get("large") or src.get("original")
            if url:
                return url
        return None
    except Exception as e:
        log.warning("pexels search failed for %r: %s", query, e)
        return None


# ── Unsplash ───────────────────────────────────────────────────────────────


def search_unsplash(query: str) -> str | None:
    key = os.environ.get("UNSPLASH_ACCESS_KEY")
    if not key or not query.strip():
        return None
    try:
        resp = http_client.get(
            UNSPLASH_API,
            params={"query": query, "per_page": 3, "orientation": "landscape"},
            headers={"Authorization": f"Client-ID {key}"},
            timeout=10,
        )
        resp.raise_for_status()
        for p in resp.json().get("results", []) or []:
            urls = p.get("urls", {}) or {}
            url = urls.get("regular") or urls.get("full") or urls.get("raw")
            if url:
                return url
        return None
    except Exception as e:
        log.warning("unsplash search failed for %r: %s", query, e)
        return None


# ── Public API ─────────────────────────────────────────────────────────────


# Order in which adapters are tried for any given query. Wikimedia is
# free + on-topic for sports/lifestyle, so it goes first.
SOURCES = (search_wikimedia, search_pexels, search_unsplash)


def find_replacement_image(title: str, description: str = "",
                           *, sources=SOURCES) -> str | None:
    """Best-effort search across the configured sources.

    Strategy:
      - Build candidate queries from `extract_entities(title)`. If the
        title doesn't yield enough proper-noun phrases (rare for sports
        news, common for "panini stickers"-style stories), fall back to
        the description.
      - For each query, try each source in order. First hit wins.
    """
    queries = list(extract_entities(title, max_terms=4))
    if len(queries) < 2 and description:
        queries.extend(extract_entities(description, max_terms=2))
    # Add a coarse "topic phrase" fallback — just the first 4 meaningful
    # words of the title joined with spaces. Useful for stories that have
    # no proper nouns at all (e.g. "Panini Football Sticker Collectors").
    bare = " ".join(title.split()[:4]) if title else ""
    if bare and bare not in queries:
        queries.append(bare)

    for q in queries:
        for src in sources:
            url = src(q)
            if url:
                log.info("replacement image via %s for %r → %s",
                         src.__name__, q, url[:80])
                return url
    return None

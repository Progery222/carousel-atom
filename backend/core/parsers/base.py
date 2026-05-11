"""Parser protocol. Each source-kind implements fetch_list() → fetch_details()."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Article:
    title: str
    url: str
    source: str
    image_url: str = ""
    description: str = ""
    published_ts: int | None = None
    extra: dict = field(default_factory=dict)


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

"""Topic config loader. Reads topics/<slug>/topic.yaml into a dataclass."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

TOPICS_DIR = Path(__file__).resolve().parent.parent / "topics"


@dataclass
class Source:
    kind: str                  # "rss" | "html" | "newsapi"
    name: str
    url: str = ""
    feed: str = ""
    article_pattern: str = ""
    query: str = ""
    # newsapi-specific knobs (ignored for other kinds)
    domains: str = ""
    language: str = "en"
    sort_by: str = "publishedAt"
    # Operational toggle so noisy sources can be muted without removing them.
    enabled: bool = True


@dataclass
class Brand:
    bg: tuple[int, int, int]
    accent: tuple[int, int, int]
    accent_light: tuple[int, int, int]
    text: tuple[int, int, int] = (255, 255, 255)
    logo_path: str = ""
    font_headline: str = ""
    font_body: str = ""


@dataclass
class CTA:
    headline: str
    subtext: str = ""


@dataclass
class CaptionConfig:
    intro: str
    hashtags: list[str]
    style: str = "bullet"
    llm_rewrite: bool = False
    # When True AND `LLM_API_KEY` is set, every article's title is
    # rewritten into a punchier @f1newsflash-style line before slides
    # are rendered. Off by default — costs ~50 tokens per article.
    llm_rewrite_titles: bool = False


@dataclass
class CarouselConfig:
    slides_per_carousel: int = 5
    news_per_carousel: int = 4
    width: int = 1080
    height: int = 1920


@dataclass
class Schedule:
    timezone: str = "UTC"
    send_hours: list[int] = field(default_factory=lambda: [9, 15, 21])


@dataclass
class TopicConfig:
    slug: str
    display_name: str
    language: str
    sources: list[Source]
    brand: Brand
    cta: CTA
    caption: CaptionConfig
    carousel: CarouselConfig
    schedule: Schedule
    telegram_chat: str | None = None
    base_dir: Path = field(default_factory=Path)
    # Optional copy overrides (see core/copy.py for the schema). Topics that
    # don't define these fall back to the global defaults.
    hook_pool: dict[str, list[dict]] = field(default_factory=dict)
    cta_pool: dict[str, list[dict]] = field(default_factory=dict)
    # Words that should drop an article from the pool when present in the
    # title. Used to filter cross-sport bleed (e.g. boxing/F1 leaking into
    # a "football" feed) and to mute specific publications you don't want.
    blocklist: list[str] = field(default_factory=list)
    # Words / phrases that should *boost* an article's score when present
    # in the title or description. Use this to make sure stories about
    # your favourite teams/players land in the carousel even on busy
    # news days. Each match adds +1.5 to the score.
    boost: list[str] = field(default_factory=list)


def _hex(s: str) -> tuple[int, int, int]:
    s = s.lstrip("#")
    return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))


def _resolve(base: Path, p: str) -> str:
    if not p:
        return ""
    if os.path.isabs(p):
        return p
    return str(base / p)


def _resolve_env(value: str | None) -> str | None:
    if not value:
        return None
    if value.startswith("env:"):
        return os.environ.get(value[4:])
    return value


def load_topic(slug: str) -> TopicConfig:
    base = TOPICS_DIR / slug
    cfg_path = base / "topic.yaml"
    if not cfg_path.exists():
        raise FileNotFoundError(f"No topic.yaml at {cfg_path}")

    with open(cfg_path, encoding="utf-8") as f:
        raw: dict[str, Any] = yaml.safe_load(f)

    sources = [Source(**s) for s in raw.get("sources", [])]

    b = raw["brand"]
    # `fonts` block is optional. When absent, designs fall back to the
    # bundled Anton/Bebas (see e.g. tiktok_news.FALLBACK_HEADLINE).
    fonts = b.get("fonts") or {}
    brand = Brand(
        bg=_hex(b["colors"]["bg"]),
        accent=_hex(b["colors"]["accent"]),
        accent_light=_hex(b["colors"]["accent_light"]),
        text=_hex(b["colors"].get("text", "#FFFFFF")),
        logo_path=_resolve(base, b.get("logo", "")),
        font_headline=_resolve(base, fonts.get("headline", "")),
        font_body=_resolve(base, fonts.get("body", "")),
    )

    cta = CTA(headline=raw["cta"]["headline"], subtext=raw["cta"].get("subtext", ""))
    cap = CaptionConfig(
        intro=raw["caption"]["intro"],
        hashtags=raw["caption"]["hashtags"],
        style=raw["caption"].get("style", "bullet"),
        llm_rewrite=raw["caption"].get("llm_rewrite", False),
        llm_rewrite_titles=raw["caption"].get("llm_rewrite_titles", False),
    )
    car = CarouselConfig(**raw.get("carousel", {}))
    sched = Schedule(**raw.get("schedule", {}))

    return TopicConfig(
        slug=raw["slug"],
        display_name=raw["display_name"],
        language=raw.get("language", "en"),
        sources=sources,
        brand=brand,
        cta=cta,
        caption=cap,
        carousel=car,
        schedule=sched,
        telegram_chat=_resolve_env(raw.get("delivery", {}).get("telegram_chat")),
        base_dir=base,
        hook_pool=_load_pool(raw.get("hook_pool"), "HookCopy"),
        cta_pool=_load_pool(raw.get("cta_pool"),   "CtaCopy"),
        blocklist=list(raw.get("blocklist") or []),
        boost=list(raw.get("boost") or []),
    )


def _load_pool(raw, kind: str) -> dict:
    """Convert raw YAML dicts into HookCopy / CtaCopy dataclasses on demand.

    Returns a dict keyed by tone ('viral'|'severe'|...) → list of dataclasses.
    Empty dict means the pool is unset and the global defaults will apply.
    """
    if not raw:
        return {}
    # Lazy import to avoid a circular dep with `core.copy`.
    from core import copy as _copy
    cls = _copy.HookCopy if kind == "HookCopy" else _copy.CtaCopy
    out: dict[str, list] = {}
    for tone, entries in raw.items():
        bucket = []
        for e in entries or []:
            try:
                bucket.append(cls(**e))
            except TypeError:
                # Forgive partial entries — we'll just skip them.
                continue
        if bucket:
            out[tone] = bucket
    return out


def list_topics() -> list[str]:
    return sorted(p.name for p in TOPICS_DIR.iterdir()
                  if p.is_dir() and (p / "topic.yaml").exists())

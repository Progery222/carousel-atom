"""Pydantic models shared by the internal `/` routes and the public
`/api/v1` router. Living in a separate module breaks the circular import
between `api.server` and `api.v1`."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class TopicOut(BaseModel):
    slug: str
    name: str
    source_count: int
    news_per_carousel: int
    featured: bool = False


class DesignOut(BaseModel):
    slug: str
    name: str
    description: str


class DeliveryOut(BaseModel):
    slug: str
    name: str
    configured: dict[str, bool]


class RenderRequest(BaseModel):
    topic: str
    design: str
    mark_seen: bool = True
    cross_topic_dedup: bool = False
    deliver: str = ""  # adapter slug, e.g. "telegram"; empty = no delivery


class ArticleIn(BaseModel):
    title: str
    url: str
    source: str
    image_url: str = ""
    description: str = ""


class RenderEditRequest(BaseModel):
    """Re-render a carousel using user-edited articles (titles, image URLs)."""
    topic: str
    design: str
    articles: list[ArticleIn]


class RenderPartialRequest(BaseModel):
    """Per-slide re-roll: items are either full articles (locked) or null
    (re-roll this slot with a fresh pick from the pipeline)."""
    topic: str
    design: str
    articles: list[Optional[ArticleIn]]


class SlideOut(BaseModel):
    index: int
    url: str  # served via /output static mount


class ArticleOut(BaseModel):
    title: str
    url: str
    source: str
    image_url: str = ""
    description: str = ""


class ArticleCandidate(ArticleOut):
    score: float = 0.0


class RenderOut(BaseModel):
    status: str
    run_id: str
    topic: str
    design: str
    caption: str
    articles: list[ArticleOut]
    slides: list[SlideOut]
    # `Optional[X]` syntax (instead of `X | None`) keeps the pydantic
    # runtime evaluator happy on Python 3.9, where PEP 604 isn't a real
    # type expression at runtime even with `from __future__ import annotations`.
    delivery: Optional[dict] = None
    diagnostics: Optional[dict] = None


class RunHistoryOut(BaseModel):
    topic: str
    run_id: str
    posted_at: int
    platform: str
    slide_count: Optional[int] = None
    caption: Optional[str] = None


class PreviewOut(BaseModel):
    topic: str
    raw: int
    fresh: int
    enriched: int
    candidates: list[ArticleCandidate]


class ScheduleTriggerRequest(BaseModel):
    design: str = "newsflash"
    deliver: str = ""
    window_min: int = 30
    dry_run: bool = False


class RewriteHeadlineRequest(BaseModel):
    title: str
    style: str = "punchier"  # punchier | factual | hook | translate_ru


class DeliverRequest(BaseModel):
    topic: str
    caption: str
    deliver: str = "telegram"

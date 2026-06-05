"""Pydantic models shared by the internal `/` routes and the public
`/api/v1` router. Living in a separate module breaks the circular import
between `api.server` and `api.v1`."""
from __future__ import annotations

from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, Field

# Topic/design slugs are filesystem directory / registry keys — lowercase
# alphanumerics and underscores. The pattern also enforces non-empty. Caps
# are generous on purpose: these models are SHARED with the internal studio
# routes, so tight limits would risk rejecting legitimate studio requests.
# An Annotated alias is the pydantic-v2-safe way to reuse a constraint across
# fields (sharing a single `Field(...)` instance is not).
Slug = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_]+$")]
# Max number of articles in an edit/partial lineup. Real carousels use
# news_per_carousel (5 across all topics today); 20 is ample headroom.
_MAX_ARTICLES = 20


class TopicOut(BaseModel):
    slug: str
    name: str
    source_count: int
    news_per_carousel: int


class DesignOut(BaseModel):
    slug: str
    name: str
    description: str


class DeliveryOut(BaseModel):
    slug: str
    name: str
    configured: dict[str, bool]


class RenderRequest(BaseModel):
    topic: Slug
    design: Slug
    mark_seen: bool = True
    cross_topic_dedup: bool = False
    # adapter slug, e.g. "telegram"; empty = no delivery (so no slug pattern)
    deliver: str = Field(default="", max_length=64)


class ArticleIn(BaseModel):
    title: str = Field(max_length=500)
    url: str = Field(max_length=2048)
    source: str = Field(max_length=200)
    image_url: str = Field(default="", max_length=2048)
    description: str = Field(default="", max_length=4000)


class RenderEditRequest(BaseModel):
    """Re-render a carousel using user-edited articles (titles, image URLs)."""
    topic: Slug
    design: Slug
    articles: list[ArticleIn] = Field(min_length=1, max_length=_MAX_ARTICLES)


class RenderPartialRequest(BaseModel):
    """Per-slide re-roll: items are either full articles (locked) or null
    (re-roll this slot with a fresh pick from the pipeline)."""
    topic: Slug
    design: Slug
    articles: list[Optional[ArticleIn]] = Field(min_length=1, max_length=_MAX_ARTICLES)


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


# ── Async jobs (public /api/v1) ─────────────────────────────────────────────


class JobOut(BaseModel):
    """Status/result envelope for an async render job.

    `job_id` is ephemeral (in-memory, single-instance — gone on restart and
    after a TTL). The durable handle is `result.run_id`: a finished run's
    slides + caption persist on disk and stay readable via
    `GET /api/v1/runs/{run_id}`.
    """
    job_id: str
    kind: str
    status: str  # queued | running | succeeded | failed
    created_at: int
    started_at: Optional[int] = None
    finished_at: Optional[int] = None
    status_url: Optional[str] = None
    result: Optional[RenderOut] = None
    error: Optional[dict] = None


class JobRenderRequest(RenderRequest):
    kind: Literal["render"] = "render"
    webhook_url: Optional[str] = Field(default=None, max_length=2048)


class JobRenderEditRequest(RenderEditRequest):
    kind: Literal["render_edit"] = "render_edit"
    webhook_url: Optional[str] = Field(default=None, max_length=2048)


class JobRenderPartialRequest(RenderPartialRequest):
    kind: Literal["render_partial"] = "render_partial"
    webhook_url: Optional[str] = Field(default=None, max_length=2048)


# Discriminated by `kind` so OpenAPI/codegen and pydantic both route the body
# to the right shape. `Literal`/`Union`/`Annotated` stay Python-3.9-safe
# (unlike PEP 604 `X | Y`), matching the repo's pydantic-compat convention.
JobRequest = Annotated[
    Union[JobRenderRequest, JobRenderEditRequest, JobRenderPartialRequest],
    Field(discriminator="kind"),
]

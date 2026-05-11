"""FastAPI app for Carousel Studio. Run from backend/:

    uvicorn api.server:app --reload --port 8000
"""
from __future__ import annotations

import io
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import hashlib
import shutil
import uuid

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core import dedup, llm
from core.caption_engine import set_llm_rewriter
from core.delivery import ADAPTERS as DELIVERY_ADAPTERS
from core.http import prune_dir_older_than
from core.log import get_logger
from core.parsers.base import Article
from core.pipeline import (
    OUTPUT_DIR,
    preview_articles,
    prune_old_runs,
    run_once,
    select_fresh_candidates,
)
from core.scheduler import due_topics, run_due_topics
from core.topic_loader import list_topics, load_topic
from designs import get_design, list_designs

log = get_logger("api")


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    dedup.init_db()
    # Auto-prune the seen-store at startup so the DB doesn't grow forever.
    pruned = dedup.prune_seen(days=int(os.environ.get("CAROUSEL_PRUNE_DAYS", "180")))
    if pruned:
        log.info("startup prune: dropped %d old seen rows", pruned)
    # Trim the rendered-output and image-verify caches so they don't
    # accumulate gigabytes over months of use. Posted runs (still in the
    # dedup `posts` table) are preserved so studio history keeps working.
    cache_days = int(os.environ.get("CAROUSEL_CACHE_DAYS", "30"))
    verify_cache = OUTPUT_DIR / "_verify_cache"
    runs_pruned = prune_old_runs(cache_days)
    verify_pruned = prune_dir_older_than(verify_cache, cache_days)
    if runs_pruned or verify_pruned:
        log.info("startup prune: %d old run dirs, %d stale verify-cache files",
                 runs_pruned, verify_pruned)
    # Wire the optional LLM rewriter if env is configured.
    rewriter = llm.caption_rewriter()
    if rewriter is not None:
        set_llm_rewriter(rewriter)
        log.info("LLM caption rewriter enabled (%s)",
                 os.environ.get("LLM_MODEL", "gpt-4o-mini"))
    log.info("startup ok · %d topics · %d designs · %d delivery adapters",
             len(list_topics()), len(list_designs()), len(DELIVERY_ADAPTERS))
    yield


app = FastAPI(title="Carousel Studio", lifespan=_lifespan)

# CORS — defaults are the Vite dev server, but the user can extend via env
# without touching code (e.g. when running on a different port).
ALLOWED_ORIGINS = [
    o.strip() for o in os.environ.get(
        "CAROUSEL_CORS",
        "http://localhost:5173,http://127.0.0.1:5173",
    ).split(",") if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/output", StaticFiles(directory=str(OUTPUT_DIR)), name="output")


# ── Schemas ─────────────────────────────────────────────────────────────────


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


# ── Routes ──────────────────────────────────────────────────────────────────


@app.get("/topics", response_model=list[TopicOut])
def topics():
    out: list[TopicOut] = []
    for slug in list_topics():
        t = load_topic(slug)
        out.append(TopicOut(
            slug=t.slug,
            name=t.display_name,
            source_count=len(t.sources),
            news_per_carousel=t.carousel.news_per_carousel,
        ))
    return out


@app.get("/designs", response_model=list[DesignOut])
def designs():
    return [
        DesignOut(slug=d.slug, name=d.name, description=d.description)
        for d in list_designs()
    ]


@app.get("/deliveries", response_model=list[DeliveryOut])
def deliveries():
    """Which delivery adapters exist and which topics they're configured for."""
    out: list[DeliveryOut] = []
    for slug, adapter in DELIVERY_ADAPTERS.items():
        configured = {}
        for t_slug in list_topics():
            t = load_topic(t_slug)
            try:
                configured[t_slug] = bool(adapter.is_configured(t))
            except Exception:
                configured[t_slug] = False
        out.append(DeliveryOut(slug=slug, name=getattr(adapter, "name", slug),
                               configured=configured))
    return out


def _slide_url(path_str: str) -> str:
    p = Path(path_str)
    rel = p.relative_to(OUTPUT_DIR)
    return f"/output/{rel.as_posix()}"


def _to_render_out(result: dict) -> RenderOut:
    slides = [
        SlideOut(index=i, url=_slide_url(p))
        for i, p in enumerate(result["slide_paths"])
    ]
    return RenderOut(
        status="ok",
        run_id=result["run_id"],
        topic=result["topic"],
        design=result["design"],
        caption=result["caption"],
        articles=[ArticleOut(**a) for a in result["articles"]],
        slides=slides,
        delivery=result.get("delivery"),
        diagnostics=result.get("diagnostics"),
    )


@app.post("/render", response_model=RenderOut)
def render(req: RenderRequest):
    """Pull fresh news, render the carousel, return slide URLs + caption."""
    result = run_once(
        req.topic, req.design,
        mark_seen=req.mark_seen,
        cross_topic_dedup=req.cross_topic_dedup,
        deliver=req.deliver,
    )
    if result["status"] != "ok":
        raise HTTPException(status_code=409, detail=result)
    return _to_render_out(result)


@app.post("/render/edit", response_model=RenderOut)
def render_edit(req: RenderEditRequest):
    """Re-render an existing carousel after the user edited titles, descriptions
    or swapped image URLs in the studio. Skips network fetching entirely.
    """
    if not req.articles:
        raise HTTPException(status_code=400, detail="no articles supplied")
    overrides = [
        Article(
            title=a.title.strip(),
            url=a.url,
            source=a.source,
            image_url=a.image_url,
            description=a.description,
        )
        for a in req.articles
    ]
    result = run_once(
        req.topic, req.design,
        mark_seen=False,
        override_articles=overrides,
    )
    if result["status"] != "ok":
        raise HTTPException(status_code=409, detail=result)
    return _to_render_out(result)


@app.post("/render/partial", response_model=RenderOut)
def render_partial(req: RenderPartialRequest):
    """Re-render a carousel where some slots are locked and some need a
    fresh story. `articles[i] == null` marks slot `i` for re-roll. The
    pipeline picks `count(null)` fresh articles excluding the URLs of
    locked slots, then renders the stitched lineup.
    """
    if not req.articles:
        raise HTTPException(status_code=400, detail="no articles supplied")
    null_positions = [i for i, a in enumerate(req.articles) if a is None]
    if not null_positions:
        # Nothing to re-roll — fall through to /render/edit semantics.
        edit_req = RenderEditRequest(
            topic=req.topic, design=req.design,
            articles=[a for a in req.articles if a is not None],
        )
        return render_edit(edit_req)

    locked_urls = {a.url for a in req.articles if a is not None and a.url}
    fresh = select_fresh_candidates(
        req.topic,
        exclude_urls=locked_urls,
        count=len(null_positions),
    )
    if len(fresh) < len(null_positions):
        raise HTTPException(
            status_code=409,
            detail={
                "status": "no_fresh",
                "message": f"only {len(fresh)} fresh articles found, "
                           f"needed {len(null_positions)}",
            },
        )

    fresh_iter = iter(fresh)
    stitched: list[Article] = []
    for a in req.articles:
        if a is None:
            stitched.append(next(fresh_iter))
        else:
            stitched.append(Article(
                title=a.title.strip(),
                url=a.url,
                source=a.source,
                image_url=a.image_url,
                description=a.description,
            ))

    result = run_once(
        req.topic, req.design,
        mark_seen=False,
        override_articles=stitched,
    )
    if result["status"] != "ok":
        raise HTTPException(status_code=409, detail=result)
    return _to_render_out(result)


@app.get("/preview/articles", response_model=PreviewOut)
def preview(topic: str, limit: int = 12):
    """Run quality+scoring without rendering — used to show candidates."""
    if topic not in list_topics():
        raise HTTPException(status_code=404, detail="unknown topic")
    return preview_articles(topic, limit=limit)


@app.get("/runs", response_model=list[RunHistoryOut])
def runs(limit: int = 30):
    """Last N posted runs across all topics — powers the studio history."""
    return [RunHistoryOut(**r) for r in dedup.recent_posts(limit=limit)]


@app.post("/dedup/reset/{topic}")
def dedup_reset(topic: str):
    """Wipe the seen-store for a topic so old stories become eligible again."""
    if topic not in list_topics():
        raise HTTPException(status_code=404, detail="unknown topic")
    deleted = dedup.reset_topic(topic)
    return {"topic": topic, "deleted": deleted}


@app.post("/dedup/prune")
def dedup_prune(days: int = 90):
    deleted = dedup.prune_seen(days=days)
    return {"deleted": deleted, "older_than_days": days}


class ScheduleTriggerRequest(BaseModel):
    design: str = "newsflash"
    deliver: str = ""
    window_min: int = 30
    dry_run: bool = False


@app.get("/schedule/due")
def schedule_due(window_min: int = 30):
    """List topic slugs that are due to run *right now* per their schedule."""
    return {"due": due_topics(window_min=window_min)}


@app.post("/schedule/trigger")
def schedule_trigger(req: ScheduleTriggerRequest):
    """Cron entrypoint — render every due topic with the chosen design.

    Designed to be called from launchd / cron / a GitHub Action every
    ~30 minutes. The window check makes the call idempotent within a
    half-hour band so missed cron ticks still publish on time.
    """
    return run_due_topics(
        design=req.design,
        deliver=req.deliver,
        window_min=req.window_min,
        dry_run=req.dry_run,
    )


class RewriteHeadlineRequest(BaseModel):
    title: str
    style: str = "punchier"  # punchier | factual | hook | translate_ru


@app.post("/llm/rewrite-headline")
def rewrite_headline(req: RewriteHeadlineRequest):
    """LLM-rewrite a single headline in the chosen style. Returns the
    rewritten title, or the original if the LLM is not configured."""
    style = req.style if req.style in llm.HEADLINE_STYLES else "punchier"
    rewriter = llm.headline_rewriter(style=style)
    if rewriter is None:
        raise HTTPException(
            status_code=503,
            detail="LLM not configured (set LLM_API_KEY env var)",
        )
    rewritten = rewriter(req.title)
    return {"title": rewritten, "style": req.style}


class DeliverRequest(BaseModel):
    topic: str
    caption: str
    deliver: str = "telegram"


@app.post("/deliver/{run_id}")
def deliver_run(run_id: str, req: DeliverRequest):
    """Push an already-rendered run to a delivery adapter (Telegram by default).

    Used by the studio's `Send to Telegram` button — the user can review
    edits in the preview, then publish without re-running the pipeline.
    Logs the delivery into the posts table so it shows up under `/runs`.
    """
    run_dir = OUTPUT_DIR / req.topic / run_id
    if not run_dir.exists():
        raise HTTPException(status_code=404, detail=f"run {run_id} not found")
    slide_paths = sorted(str(p) for p in run_dir.glob("slide_*.png"))
    if not slide_paths:
        raise HTTPException(status_code=409, detail="no slide PNGs in run dir")

    adapter = DELIVERY_ADAPTERS.get(req.deliver)
    if adapter is None:
        raise HTTPException(status_code=400, detail=f"unknown adapter: {req.deliver}")
    topic = load_topic(req.topic)
    if not adapter.is_configured(topic):
        raise HTTPException(
            status_code=400,
            detail=f"{req.deliver} not configured for topic {req.topic}",
        )

    result = adapter.send(topic, {
        "slide_paths": slide_paths,
        "caption": req.caption,
    })
    if result.ok:
        external_id = ",".join(str(i) for i in result.msg_ids) if result.msg_ids else None
        dedup.log_post(req.topic, run_id, req.deliver, req.caption,
                       len(slide_paths), external_id=external_id)
    return {
        "ok": result.ok,
        "message": result.message,
        "msg_ids": result.msg_ids,
    }


def _detect_image_kind(raw: bytes) -> str | None:
    """Match real image magic bytes — content-type and extension are
    user-controlled, so we don't trust them. Returns the file suffix or
    None if the payload doesn't look like one of our supported formats."""
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if raw.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if len(raw) >= 12 and raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "webp"
    return None


@app.post("/upload-image")
async def upload_image(request: Request, file: UploadFile = File(...)):
    """Save an uploaded image into /output/_uploads/ and return a stable
    URL the SlideEditor can paste into an article's image_url. Used when
    the user wants to override the hero photo with their own asset
    (better resolution / brand shot / etc).

    The file is content-hashed so the same upload reuses one path —
    duplicate uploads don't litter the disk.
    """
    raw = await file.read()
    if len(raw) > 12 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="image too large (12MB max)")
    suffix = _detect_image_kind(raw)
    if suffix is None:
        # Reject everything we can't positively identify (SVG, HTML, EXE,
        # corrupt files). Content-type and filename can lie; magic bytes
        # can't.
        raise HTTPException(status_code=400, detail="not a valid PNG/JPEG/WEBP image")
    # Second-pass sanity: make sure Pillow can actually decode it. Catches
    # truncated/corrupt files that have the right header but a broken body.
    try:
        from PIL import Image
        Image.open(io.BytesIO(raw)).verify()
    except Exception:
        raise HTTPException(status_code=400, detail="image is corrupt or unreadable")
    digest = hashlib.sha1(raw).hexdigest()[:16]
    save_dir = OUTPUT_DIR / "_uploads"
    save_dir.mkdir(parents=True, exist_ok=True)
    dst = save_dir / f"{digest}.{suffix}"
    if not dst.exists():
        with open(dst, "wb") as f:
            f.write(raw)
    # Return an absolute URL so the pipeline's image-fetcher can hit it
    # via the same code path as a real publisher URL. Uses the request's
    # host so it works on any port the user binds uvicorn to.
    base = str(request.base_url).rstrip("/")
    return {
        "url": f"{base}/output/_uploads/{dst.name}",
        "size": len(raw),
        "filename": file.filename,
    }


@app.get("/health")
def health():
    """Rich health snapshot used by the studio status pill."""
    topic_stats: dict[str, dict] = {}
    for slug in list_topics():
        topic_stats[slug] = dedup.stats(slug)
    return {
        "ok": True,
        "designs": [d.slug for d in list_designs()],
        "topics": list_topics(),
        "deliveries": list(DELIVERY_ADAPTERS),
        "llm_enabled": bool(llm.caption_rewriter()) if llm._is_enabled() else False,
        "stats": topic_stats,
    }


# ── Frontend static mount ───────────────────────────────────────────────────
#
# In production (single-service Railway deploy) the Dockerfile builds the
# Vite app and copies it to /app/frontend/dist. Mount it at "/" with
# html=True so client-side routing falls back to index.html. This MUST be
# the very last mount — once mounted on "/", any subsequent FastAPI
# route registration would be shadowed.
_FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if _FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIST), html=True), name="frontend")
    log.info("serving frontend from %s", _FRONTEND_DIST)
else:
    log.info("no frontend build at %s — running API-only", _FRONTEND_DIST)

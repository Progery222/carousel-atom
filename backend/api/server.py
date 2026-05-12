"""FastAPI app for Carousel Studio. Run from backend/:

    uvicorn api.server:app --reload --port 8000
"""
from __future__ import annotations

import io
import os
from contextlib import asynccontextmanager
from pathlib import Path

import hashlib
import time
import uuid

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware

from api.rate_limit import limiter
from api.schemas import (
    ArticleOut,
    DeliverRequest,
    DeliveryOut,
    DesignOut,
    PreviewOut,
    RenderEditRequest,
    RenderOut,
    RenderPartialRequest,
    RenderRequest,
    RewriteHeadlineRequest,
    RunHistoryOut,
    ScheduleTriggerRequest,
    SlideOut,
    TopicOut,
)
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
from designs import list_designs

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

# Rate limiter is owned by the public /api/v1 router but the limiter
# state and exception handler are registered here so it ships with the app.
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def _rate_limit_handler(request: Request, exc: RateLimitExceeded):
    rid = getattr(request.state, "request_id", "")
    return JSONResponse(
        status_code=429,
        content={
            "error": {
                "code": "rate_limited",
                "message": f"rate limit exceeded: {exc.detail}",
                "request_id": rid,
            }
        },
        headers={"Retry-After": "60"},
    )


@app.exception_handler(HTTPException)
async def _http_exc_handler(request: Request, exc: HTTPException):
    """Unified error shape for /api/v1 — internal routes keep FastAPI defaults
    so the studio frontend (which already parses `{detail: ...}`) is unaffected.
    """
    rid = getattr(request.state, "request_id", "")
    if request.url.path.startswith("/api/v1/"):
        # Map common HTTP codes to stable string codes the client can switch on.
        code_map = {
            400: "bad_request", 401: "unauthorized", 403: "forbidden",
            404: "not_found", 409: "conflict", 413: "payload_too_large",
            429: "rate_limited", 503: "service_unavailable",
        }
        code = code_map.get(exc.status_code, f"http_{exc.status_code}")
        # Pipeline errors (409) embed the diagnostics dict as detail. Keep it
        # inside the unified envelope so consumers can still drill in.
        if isinstance(exc.detail, dict):
            payload: dict = {
                "code": exc.detail.get("status", code),
                "message": exc.detail.get("message", str(exc.detail)),
                "request_id": rid,
                "details": exc.detail,
            }
        else:
            payload = {"code": code, "message": str(exc.detail), "request_id": rid}
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": payload},
            headers=exc.headers or {},
        )
    # Default FastAPI shape for everything else.
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers=exc.headers or {},
    )


class _RequestContextMiddleware(BaseHTTPMiddleware):
    """Generates X-Request-ID and logs method/path/status/duration for /api/v1."""

    _log = get_logger("api.v1")

    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        request.state.request_id = rid
        is_public = request.url.path.startswith("/api/v1/")
        start = time.monotonic()
        try:
            response = await call_next(request)
        except Exception:
            if is_public:
                dur_ms = int((time.monotonic() - start) * 1000)
                self._log.exception("%s %s · 500 · %dms · rid=%s",
                                    request.method, request.url.path, dur_ms, rid)
            raise
        response.headers["X-Request-ID"] = rid
        if is_public:
            dur_ms = int((time.monotonic() - start) * 1000)
            key_name = getattr(getattr(request.state, "api_key", None), "name", "-")
            self._log.info("%s %s · %d · %dms · key=%s · rid=%s",
                           request.method, request.url.path,
                           response.status_code, dur_ms, key_name, rid)
        return response


app.add_middleware(_RequestContextMiddleware)
# Note: we deliberately do NOT register `SlowAPIMiddleware`. That
# middleware sets `request.state._rate_limiting_complete = True` before
# the endpoint runs, which causes the `@limiter.limit(...)` decorator
# inside the endpoint to skip its check (slowapi.extension treats the
# flag as "limit already enforced earlier"). Decorator-based limits
# work standalone; the middleware is only needed for shared
# `default_limits` applied to every route — which we don't want.

# CORS — defaults are the Vite dev server, but the user can extend via env
# without touching code (e.g. when running on a different port).
ALLOWED_ORIGINS = [
    o.strip() for o in os.environ.get(
        "CAROUSEL_CORS",
        "http://localhost:5173,http://127.0.0.1:5173",
    ).split(",") if o.strip()
]

# Separate CORS list for the public /api/v1 router. Defaults to "*"
# because the typical caller is server-to-server (no browser, no Origin).
# Set to a comma list of origins if you need to call /api/v1 from a browser app.
API_V1_ORIGINS = [
    o.strip() for o in os.environ.get("CAROUSEL_API_CORS", "*").split(",")
    if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=list({*ALLOWED_ORIGINS, *API_V1_ORIGINS}),
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID", "Retry-After"],
)

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/output", StaticFiles(directory=str(OUTPUT_DIR)), name="output")


# ── Routes ──────────────────────────────────────────────────────────────────


@app.get("/topics", response_model=list[TopicOut])
def topics():
    return list_topics_impl()


@app.get("/designs", response_model=list[DesignOut])
def designs():
    return list_designs_impl()


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


def _slide_url(path_str: str, *, base: str = "") -> str:
    p = Path(path_str)
    rel = p.relative_to(OUTPUT_DIR)
    suffix = f"/output/{rel.as_posix()}"
    return f"{base.rstrip('/')}{suffix}" if base else suffix


def _to_render_out(result: dict, *, base: str = "") -> RenderOut:
    slides = [
        SlideOut(index=i, url=_slide_url(p, base=base))
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


# ── Shared impl funcs (used by both internal /render and public /api/v1) ────


def list_topics_impl() -> list[TopicOut]:
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


def list_designs_impl() -> list[DesignOut]:
    return [
        DesignOut(slug=d.slug, name=d.name, description=d.description)
        for d in list_designs()
    ]


def preview_impl(topic: str, limit: int = 12) -> PreviewOut:
    if topic not in list_topics():
        raise HTTPException(status_code=404, detail="unknown topic")
    data = preview_articles(topic, limit=limit)
    return PreviewOut(**data)


def render_impl(req: RenderRequest, *, base: str = "") -> RenderOut:
    result = run_once(
        req.topic, req.design,
        mark_seen=req.mark_seen,
        cross_topic_dedup=req.cross_topic_dedup,
        deliver=req.deliver,
    )
    if result["status"] != "ok":
        raise HTTPException(status_code=409, detail=result)
    return _to_render_out(result, base=base)


def render_edit_impl(req: RenderEditRequest, *, base: str = "") -> RenderOut:
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
    return _to_render_out(result, base=base)


def render_partial_impl(req: RenderPartialRequest, *, base: str = "") -> RenderOut:
    if not req.articles:
        raise HTTPException(status_code=400, detail="no articles supplied")
    null_positions = [i for i, a in enumerate(req.articles) if a is None]
    if not null_positions:
        edit_req = RenderEditRequest(
            topic=req.topic, design=req.design,
            articles=[a for a in req.articles if a is not None],
        )
        return render_edit_impl(edit_req, base=base)

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
    return _to_render_out(result, base=base)


# ── Internal routes (used by the studio frontend) ──────────────────────────


@app.post("/render", response_model=RenderOut)
def render(req: RenderRequest):
    """Pull fresh news, render the carousel, return slide URLs + caption."""
    return render_impl(req)


@app.post("/render/edit", response_model=RenderOut)
def render_edit(req: RenderEditRequest):
    """Re-render an existing carousel after the user edited titles, descriptions
    or swapped image URLs in the studio. Skips network fetching entirely.
    """
    return render_edit_impl(req)


@app.post("/render/partial", response_model=RenderOut)
def render_partial(req: RenderPartialRequest):
    """Re-render a carousel where some slots are locked and some need a
    fresh story. `articles[i] == null` marks slot `i` for re-roll. The
    pipeline picks `count(null)` fresh articles excluding the URLs of
    locked slots, then renders the stitched lineup.
    """
    return render_partial_impl(req)


@app.get("/preview/articles", response_model=PreviewOut)
def preview(topic: str, limit: int = 12):
    """Run quality+scoring without rendering — used to show candidates."""
    return preview_impl(topic, limit=limit)


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


# ── Public API (/api/v1) ────────────────────────────────────────────────────
#
# The public router is included AFTER the internal routes are registered
# but BEFORE the frontend SPA mount (which captures everything under "/").
from api.v1 import public_health, router as v1_router  # noqa: E402


@app.get("/api/v1/health", tags=["Public API v1"], summary="Liveness ping")
def v1_health():
    """Auth-free liveness check for the public API."""
    return public_health()


app.include_router(v1_router)


# Override the Swagger UI / OpenAPI for the public API so consumers see
# only the versioned surface. The default /docs and /openapi.json still
# cover the full app (internal + public).
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html  # noqa: E402
from fastapi.openapi.utils import get_openapi  # noqa: E402


@app.get("/api/v1/openapi.json", include_in_schema=False)
def v1_openapi():
    """OpenAPI 3.1 schema filtered to /api/v1/* routes only."""
    public_routes = [r for r in app.routes
                     if getattr(r, "path", "").startswith("/api/v1")]
    return get_openapi(
        title="Carousel Studio Public API",
        version="1.0.0",
        description=(
            "Server-to-server API for generating news carousels.\n\n"
            "Auth: `X-API-Key` header (set via `CAROUSEL_API_KEYS` on the server)."
        ),
        routes=public_routes,
    )


@app.get("/api/v1/docs", include_in_schema=False)
def v1_swagger():
    return get_swagger_ui_html(
        openapi_url="/api/v1/openapi.json",
        title="Carousel Studio API · Swagger UI",
    )


@app.get("/api/v1/redoc", include_in_schema=False)
def v1_redoc():
    return get_redoc_html(
        openapi_url="/api/v1/openapi.json",
        title="Carousel Studio API · ReDoc",
    )


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

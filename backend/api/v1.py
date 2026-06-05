"""Public /api/v1 router for Carousel Studio.

External services authenticate with `X-API-Key` (configured via the
`CAROUSEL_API_KEYS` env var) and get a stable, versioned surface for:

- listing topics & designs (discovery)
- previewing fresh candidates
- rendering carousels (full, edit, partial)
- downloading the rendered run as a ZIP

All handlers are thin wrappers over `api.server` impl functions, so the
behavior matches the studio frontend exactly. Errors come back as
`{"error": {"code": ..., "message": ..., "request_id": ...}}` via the
unified handler in `api.server`.
"""
from __future__ import annotations

import io
import json
import os
import zipfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from api.auth import ApiKeyInfo, verify_api_key
from api.jobs import get_store
from api.rate_limit import HEAVY_LIMIT, LIGHT_LIMIT, limiter
from api.schemas import (
    JobOut,
    JobRequest,
    PreviewOut,
    RenderEditRequest,
    RenderOut,
    RenderPartialRequest,
    RenderRequest,
)
from core.pipeline import OUTPUT_DIR
from core.topic_loader import list_topics


def _attach_key(info: ApiKeyInfo, request: Request) -> ApiKeyInfo:
    """Stash the matched key on request.state so the rate-limiter and
    logging middleware can read it. The limiter's key_func reads from
    request.state.api_key directly."""
    request.state.api_key = info
    return info


def _key_dep(request: Request, info: ApiKeyInfo = Depends(verify_api_key)) -> ApiKeyInfo:
    return _attach_key(info, request)


router = APIRouter(
    prefix="/api/v1",
    tags=["Public API v1"],
    dependencies=[Depends(_key_dep)],
)


def _public_base(request: Request) -> str:
    """Base URL for absolute asset links in responses.

    Order of precedence:
    1. `PUBLIC_BASE_URL` env var (set this to the public origin behind your
       reverse proxy / Tailscale Funnel).
    2. `request.base_url` — works when the app is hit directly.
    """
    env = os.environ.get("PUBLIC_BASE_URL", "").strip().rstrip("/")
    if env:
        return env
    return str(request.base_url).rstrip("/")


# ── Discovery ──────────────────────────────────────────────────────────────


@router.get("/topics", summary="List available topics")
@limiter.limit(LIGHT_LIMIT)
def v1_topics(request: Request):
    from api.server import list_topics_impl
    return list_topics_impl()


@router.get("/designs", summary="List available designs")
@limiter.limit(LIGHT_LIMIT)
def v1_designs(request: Request):
    from api.server import list_designs_impl
    return list_designs_impl()


# ── Preview ────────────────────────────────────────────────────────────────


@router.get("/preview/articles", response_model=PreviewOut,
            summary="Preview fresh article candidates")
@limiter.limit(LIGHT_LIMIT)
def v1_preview(request: Request, topic: str,
               limit: int = Query(12, ge=1, le=50)):
    from api.server import preview_impl
    return preview_impl(topic, limit=limit)


# ── Render ─────────────────────────────────────────────────────────────────


@router.post("/render", response_model=RenderOut, summary="Render a fresh carousel")
@limiter.limit(HEAVY_LIMIT)
def v1_render(request: Request, req: RenderRequest):
    from api.server import render_impl
    return render_impl(req, base=_public_base(request))


@router.post("/render/edit", response_model=RenderOut,
             summary="Re-render with user-edited articles")
@limiter.limit(HEAVY_LIMIT)
def v1_render_edit(request: Request, req: RenderEditRequest):
    from api.server import render_edit_impl
    return render_edit_impl(req, base=_public_base(request))


@router.post("/render/partial", response_model=RenderOut,
             summary="Per-slot re-roll render")
@limiter.limit(HEAVY_LIMIT)
def v1_render_partial(request: Request, req: RenderPartialRequest):
    from api.server import render_partial_impl
    return render_partial_impl(req, base=_public_base(request))


# ── ZIP export ─────────────────────────────────────────────────────────────


def _resolve_run_dir(run_id: str, topic: str | None) -> Path:
    """Locate the run directory under OUTPUT_DIR/<topic>/<run_id>.

    `run_id` format is `{topic}_{design}_{ts}_{uid}` — we can recover the
    topic by splitting, but the caller can also pass it explicitly via
    query param if the slug contains underscores (e.g. `red_bull`).

    Security: `run_id` and `topic` become path segments. A query-string
    `topic` bypasses the ASGI path-normalization that strips `..`, so we
    reject path separators / `..` up front AND verify the resolved path is
    contained within OUTPUT_DIR before any filesystem access — otherwise
    `?topic=../../x` would escape the output tree (path traversal).
    """
    if not run_id or "/" in run_id or "\\" in run_id or ".." in run_id:
        raise HTTPException(status_code=404, detail=f"run not found: {run_id}")
    candidates: list[str] = []
    if topic:
        candidates.append(topic)
    else:
        # Heuristic: try every known topic prefix until one matches a real dir.
        for slug in list_topics():
            if run_id.startswith(f"{slug}_"):
                candidates.append(slug)
    root = OUTPUT_DIR.resolve()
    for slug in candidates:
        if "/" in slug or "\\" in slug or ".." in slug:
            continue
        try:
            resolved = (OUTPUT_DIR / slug / run_id).resolve()
        except (OSError, ValueError):
            continue
        if not resolved.is_relative_to(root):
            continue
        if resolved.exists():
            return resolved
    raise HTTPException(status_code=404, detail=f"run not found: {run_id}")


# Sidecar written next to the slides at render time (see
# `api.server._persist_run`). Holds the caption + article metadata that the
# pipeline itself never persists to disk.
RUN_META_FILENAME = "run.json"


def _read_run_meta(run_dir: Path) -> Optional[dict]:
    """Read the `run.json` sidecar written at render time. Tolerant: returns
    None when the file is missing or unreadable (older runs predate it, or a
    crash truncated it) so callers degrade gracefully to slides-only."""
    try:
        return json.loads((run_dir / RUN_META_FILENAME).read_text(encoding="utf-8"))
    except Exception:
        return None


def _zip_stream(run_dir: Path) -> io.BytesIO:
    """Build a ZIP of all slide_*.png files in the run dir, plus
    metadata.json (run_id, topic, design, slide count) and caption.txt.
    The caption comes from the `run.json` sidecar (falling back to a legacy
    caption.txt file if one is present). Buffered in memory — runs are
    small (<10MB)."""
    buf = io.BytesIO()
    slide_paths = sorted(run_dir.glob("slide_*.png"))
    if not slide_paths:
        raise HTTPException(status_code=404, detail="no slides in run dir")
    meta = _read_run_meta(run_dir) or {}
    parts = run_dir.name.split("_")
    metadata = {
        "run_id": run_dir.name,
        "topic": meta.get("topic", run_dir.parent.name),
        "design": meta.get("design", parts[1] if len(parts) >= 2 else ""),
        "slide_count": len(slide_paths),
    }
    # Caption: prefer the persisted run.json; fall back to a legacy
    # caption.txt file next to the slides if one happens to exist.
    caption = meta.get("caption")
    if caption is None:
        legacy = run_dir / "caption.txt"
        caption = legacy.read_text(encoding="utf-8") if legacy.exists() else None
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in slide_paths:
            zf.write(p, arcname=p.name)
        if caption is not None:
            zf.writestr("caption.txt", caption)
        zf.writestr("metadata.json", json.dumps(metadata, indent=2))
    buf.seek(0)
    return buf


@router.get("/export/{run_id}.zip", summary="Download rendered run as a ZIP")
@limiter.limit(HEAVY_LIMIT)
def v1_export_zip(request: Request, run_id: str,
                  topic: Optional[str] = Query(default=None, pattern=r"^[a-z0-9_]+$")):
    run_dir = _resolve_run_dir(run_id, topic)
    buf = _zip_stream(run_dir)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{run_id}.zip"'},
    )


# ── Run details ────────────────────────────────────────────────────────────


@router.get("/runs/{run_id}", response_model=RenderOut,
            summary="Fetch a previously rendered run")
@limiter.limit(LIGHT_LIMIT)
def v1_get_run(request: Request, run_id: str,
               topic: Optional[str] = Query(default=None, pattern=r"^[a-z0-9_]+$")):
    """Re-read a finished run from disk: caption, articles and absolute slide
    URLs, reconstructed from the `run.json` sidecar (degrades to slides-only
    if the sidecar is missing — e.g. a run rendered before this existed).

    This is the durable counterpart to an async job: a `job_id` is ephemeral,
    but the `run_id` keeps working across restarts. Pass `?topic=...` if the
    run-id heuristic can't recover a slug containing underscores."""
    from api.server import _to_render_out
    run_dir = _resolve_run_dir(run_id, topic)
    slide_paths = sorted(str(p) for p in run_dir.glob("slide_*.png"))
    if not slide_paths:
        raise HTTPException(status_code=404, detail=f"no slides in run: {run_id}")
    meta = _read_run_meta(run_dir) or {}
    parts = run_dir.name.split("_")
    result = {
        "run_id": run_id,
        "topic": meta.get("topic", run_dir.parent.name),
        "design": meta.get("design", parts[1] if len(parts) >= 2 else ""),
        "caption": meta.get("caption", ""),
        "articles": meta.get("articles", []),
        "slide_paths": slide_paths,
    }
    return _to_render_out(result, base=_public_base(request))


# ── Async jobs ─────────────────────────────────────────────────────────────


def _job_to_out(job, *, base: str = "") -> JobOut:
    status_url = f"{base.rstrip('/')}/api/v1/jobs/{job.id}" if base else None
    return JobOut(
        job_id=job.id,
        kind=job.kind,
        status=job.status,
        created_at=int(job.created_at),
        started_at=int(job.started_at) if job.started_at else None,
        finished_at=int(job.finished_at) if job.finished_at else None,
        status_url=status_url,
        result=job.result,
        error=job.error,
    )


@router.post("/jobs", status_code=202, response_model=JobOut,
             summary="Submit an async render job")
@limiter.limit(HEAVY_LIMIT)
def v1_create_job(request: Request, body: JobRequest):
    """Enqueue a render and return immediately with `202` + a `job_id`. Poll
    `GET /api/v1/jobs/{job_id}` for status/result, or supply a `webhook_url`
    (https-only, SSRF-guarded) to be notified on completion. Same request body
    as the sync render endpoints, tagged with `kind`."""
    from api.server import (
        render_edit_impl,
        render_impl,
        render_partial_impl,
        _validate_topic_design,
    )
    base = _public_base(request)
    # Fail fast on an unknown topic/design instead of returning 202 then failing.
    _validate_topic_design(body.topic, body.design)
    impls = {
        "render": render_impl,
        "render_edit": render_edit_impl,
        "render_partial": render_partial_impl,
    }
    impl = impls[body.kind]

    def _fn():
        return impl(body, base=base)

    info = getattr(request.state, "api_key", None)
    job = get_store().submit(
        body.kind, _fn,
        api_key_name=getattr(info, "name", "-"),
        webhook_url=body.webhook_url or "",
        base=base,
    )
    return _job_to_out(job, base=base)


@router.get("/jobs/{job_id}", response_model=JobOut,
            summary="Get async job status & result")
@limiter.limit(LIGHT_LIMIT)
def v1_get_job(request: Request, job_id: str):
    job = get_store().get(job_id)
    if job is None:
        raise HTTPException(
            status_code=404,
            detail=(f"job not found or expired: {job_id} — if the render "
                    f"finished, fetch it by run_id via GET /api/v1/runs/{{run_id}}"),
        )
    return _job_to_out(job, base=_public_base(request))


# ── Health (no auth) ───────────────────────────────────────────────────────
#
# Mounted separately at module load time on the main app to skip auth.
# Exposed here as a function so server.py can register it.


def public_health() -> dict:
    return {"ok": True, "service": "carousel-studio", "version": "1"}

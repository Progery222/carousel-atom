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

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from api.auth import ApiKeyInfo, verify_api_key
from api.rate_limit import HEAVY_LIMIT, LIGHT_LIMIT, limiter
from api.schemas import (
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
    1. `PUBLIC_BASE_URL` env var (set this on Railway to the public origin).
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
def v1_preview(request: Request, topic: str, limit: int = 12):
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
    """
    candidates: list[str] = []
    if topic:
        candidates.append(topic)
    else:
        # Heuristic: try every known topic prefix until one matches a real dir.
        for slug in list_topics():
            if run_id.startswith(f"{slug}_"):
                candidates.append(slug)
    for slug in candidates:
        path = OUTPUT_DIR / slug / run_id
        if path.exists():
            return path
    raise HTTPException(status_code=404, detail=f"run not found: {run_id}")


def _zip_stream(run_dir: Path) -> io.BytesIO:
    """Build a ZIP of all slide_*.png files in the run dir, plus
    metadata.json (run_id, topic, design, slide count) and caption.txt
    if present. Buffered in memory — runs are small (<10MB)."""
    buf = io.BytesIO()
    slide_paths = sorted(run_dir.glob("slide_*.png"))
    if not slide_paths:
        raise HTTPException(status_code=404, detail="no slides in run dir")
    parts = run_dir.name.split("_")
    metadata = {
        "run_id": run_dir.name,
        "topic": run_dir.parent.name,
        "design": parts[1] if len(parts) >= 2 else "",
        "slide_count": len(slide_paths),
    }
    caption_file = run_dir / "caption.txt"
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in slide_paths:
            zf.write(p, arcname=p.name)
        if caption_file.exists():
            zf.write(caption_file, arcname="caption.txt")
        zf.writestr("metadata.json", json.dumps(metadata, indent=2))
    buf.seek(0)
    return buf


@router.get("/export/{run_id}.zip", summary="Download rendered run as a ZIP")
@limiter.limit(HEAVY_LIMIT)
def v1_export_zip(request: Request, run_id: str, topic: Optional[str] = None):
    run_dir = _resolve_run_dir(run_id, topic)
    buf = _zip_stream(run_dir)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{run_id}.zip"'},
    )


# ── Health (no auth) ───────────────────────────────────────────────────────
#
# Mounted separately at module load time on the main app to skip auth.
# Exposed here as a function so server.py can register it.


def public_health() -> dict:
    return {"ok": True, "service": "carousel-studio", "version": "1"}

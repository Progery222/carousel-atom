"""Public /api/v1 router for Carousel Studio — cross-service standard surface.

External services authenticate with `X-API-Key` and consume a uniform contract:
- every JSON response is `{success, data, meta:{request_id}}` (errors:
  `{success:false, error:{code,message,details?}, meta}`) — see `api.server`
  exception handlers and `api.responses.ok`;
- resources use CRUD-ish GET/POST/DELETE; service operations are
  `POST /actions/{name}`; lists are cursor-paginated (`limit` + `cursor`);
- API keys are hashed in the DB with `read`/`write`/`admin` scopes.

System endpoints (`/health`, `/meta`, `/openapi.json`) are auth-free;
everything else requires a key with a sufficient scope.
"""
from __future__ import annotations

import io
import json
import os
import shutil
import zipfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from api.auth import ApiKeyInfo, auth_dependency, require_scope
from api.jobs import get_store
from api.rate_limit import HEAVY_LIMIT, LIGHT_LIMIT, limiter
from api.responses import decode_cursor, encode_cursor, ok, paginate_sorted
from api.schemas import (
    ApiKeyCreateOut,
    ApiKeyCreateRequest,
    ApiKeyOut,
    DesignOut,
    Envelope,
    HealthOut,
    JobOut,
    JobRequest,
    MetaOut,
    Page,
    PreviewOut,
    PreviewRequest,
    RenderEditRequest,
    RenderOut,
    RenderPartialRequest,
    RenderRequest,
    RunSummary,
    TopicOut,
    VerifyOut,
)
from core import api_keys, dedup
from core.pipeline import OUTPUT_DIR
from core.topic_loader import list_topics

# Keep in sync with backend/pyproject.toml [project] version.
SERVICE_VERSION = "0.1.0"
API_VERSION = "v1"

# Auth-free system surface (health/meta). Auth'd surface for everything else;
# `auth_dependency` attaches the key to request.state for the limiter + logs.
system_router = APIRouter(prefix="/api/v1", tags=["System"])
router = APIRouter(prefix="/api/v1", tags=["Public API v1"],
                   dependencies=[Depends(auth_dependency)])


def _public_base(request: Request) -> str:
    """Base URL for absolute asset links. `PUBLIC_BASE_URL` (behind a reverse
    proxy / Tailscale Funnel) wins, else the request host."""
    env = os.environ.get("PUBLIC_BASE_URL", "").strip().rstrip("/")
    return env if env else str(request.base_url).rstrip("/")


# ── System (no auth) ─────────────────────────────────────────────────────────


@system_router.get("/health", response_model=Envelope[HealthOut], summary="Liveness ping")
def v1_health(request: Request):
    return ok(HealthOut(status="ok", version=SERVICE_VERSION), request)


@system_router.get("/meta", response_model=Envelope[MetaOut], summary="Service metadata / contract")
@limiter.limit(LIGHT_LIMIT)
def v1_meta(request: Request):
    data = MetaOut(
        service="carousel-studio",
        version=SERVICE_VERSION,
        api_version=API_VERSION,
        capabilities={
            "resources": ["topics", "designs", "runs", "jobs", "api-keys"],
            "actions": ["render", "render-edit", "render-partial", "preview"],
        },
        scopes=["read", "write", "admin"],
        pagination={"style": "cursor", "limit_param": "limit",
                    "cursor_param": "cursor", "default_limit": 20, "max_limit": 100},
        auth={"type": "apiKey", "in": "header", "name": "X-API-Key"},
    )
    return ok(data, request)


# ── Auth introspection ───────────────────────────────────────────────────────


@router.get("/auth/verify", response_model=Envelope[VerifyOut],
            summary="Verify the calling API key")
@limiter.limit(LIGHT_LIMIT)
def v1_auth_verify(request: Request, info: ApiKeyInfo = Depends(auth_dependency)):
    return ok(VerifyOut(key_id=info.key_id, name=info.name,
                        scopes=sorted(info.scopes)), request)


# ── Discovery resources ──────────────────────────────────────────────────────


@router.get("/topics", response_model=Envelope[list[TopicOut]],
            dependencies=[Depends(require_scope("read"))], summary="List topics")
@limiter.limit(LIGHT_LIMIT)
def v1_topics(request: Request):
    from api.server import list_topics_impl
    return ok(list_topics_impl(), request)


@router.get("/topics/{slug}", response_model=Envelope[TopicOut],
            dependencies=[Depends(require_scope("read"))], summary="Get a topic")
@limiter.limit(LIGHT_LIMIT)
def v1_topic(request: Request, slug: str):
    from api.server import list_topics_impl
    for t in list_topics_impl():
        if t.slug == slug:
            return ok(t, request)
    raise HTTPException(status_code=404, detail=f"unknown topic: {slug}")


@router.get("/designs", response_model=Envelope[list[DesignOut]],
            dependencies=[Depends(require_scope("read"))], summary="List designs")
@limiter.limit(LIGHT_LIMIT)
def v1_designs(request: Request):
    from api.server import list_designs_impl
    return ok(list_designs_impl(), request)


@router.get("/designs/{slug}", response_model=Envelope[DesignOut],
            dependencies=[Depends(require_scope("read"))], summary="Get a design")
@limiter.limit(LIGHT_LIMIT)
def v1_design(request: Request, slug: str):
    from api.server import list_designs_impl
    for d in list_designs_impl():
        if d.slug == slug:
            return ok(d, request)
    raise HTTPException(status_code=404, detail=f"unknown design: {slug}")


# ── Actions (service operations) ─────────────────────────────────────────────


@router.post("/actions/preview", response_model=Envelope[PreviewOut],
             dependencies=[Depends(require_scope("read"))],
             summary="Preview fresh article candidates (no render)")
@limiter.limit(LIGHT_LIMIT)
def v1_action_preview(request: Request, body: PreviewRequest):
    from api.server import preview_impl
    return ok(preview_impl(body.topic, limit=body.limit), request)


@router.post("/actions/render", response_model=Envelope[RenderOut],
             dependencies=[Depends(require_scope("write"))],
             summary="Render a fresh carousel")
@limiter.limit(HEAVY_LIMIT)
def v1_action_render(request: Request, body: RenderRequest):
    from api.server import render_impl
    return ok(render_impl(body, base=_public_base(request)), request)


@router.post("/actions/render-edit", response_model=Envelope[RenderOut],
             dependencies=[Depends(require_scope("write"))],
             summary="Re-render with user-edited articles")
@limiter.limit(HEAVY_LIMIT)
def v1_action_render_edit(request: Request, body: RenderEditRequest):
    from api.server import render_edit_impl
    return ok(render_edit_impl(body, base=_public_base(request)), request)


@router.post("/actions/render-partial", response_model=Envelope[RenderOut],
             dependencies=[Depends(require_scope("write"))],
             summary="Per-slot re-roll render")
@limiter.limit(HEAVY_LIMIT)
def v1_action_render_partial(request: Request, body: RenderPartialRequest):
    from api.server import render_partial_impl
    return ok(render_partial_impl(body, base=_public_base(request)), request)


# ── Runs ─────────────────────────────────────────────────────────────────────


def _resolve_run_dir(run_id: str, topic: str | None) -> Path:
    """Locate OUTPUT_DIR/<topic>/<run_id>, rejecting path traversal.

    `run_id`/`topic` become path segments; a query-string `topic` bypasses ASGI
    path normalization, so we reject separators/`..` and verify the resolved
    path stays inside OUTPUT_DIR before any filesystem access."""
    if not run_id or "/" in run_id or "\\" in run_id or ".." in run_id:
        raise HTTPException(status_code=404, detail=f"run not found: {run_id}")
    candidates: list[str] = []
    if topic:
        candidates.append(topic)
    else:
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


RUN_META_FILENAME = "run.json"


def _read_run_meta(run_dir: Path) -> Optional[dict]:
    """Read the `run.json` sidecar (caption + articles). None if missing/broken
    so callers degrade to slides-only."""
    try:
        return json.loads((run_dir / RUN_META_FILENAME).read_text(encoding="utf-8"))
    except Exception:
        return None


def _zip_stream(run_dir: Path) -> io.BytesIO:
    """ZIP of slide_*.png + caption.txt (from run.json) + metadata.json."""
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


@router.get("/runs", response_model=Envelope[Page[RunSummary]],
            dependencies=[Depends(require_scope("read"))],
            summary="List rendered runs (cursor-paginated)")
@limiter.limit(LIGHT_LIMIT)
def v1_list_runs(request: Request,
                 limit: int = Query(20, ge=1, le=100),
                 cursor: Optional[str] = Query(default=None)):
    after = decode_cursor(cursor)
    rows, has_more = dedup.list_runs(limit=limit, cursor=after)
    next_cursor = None
    if has_more and rows:
        last = rows[-1]
        next_cursor = encode_cursor(last["created_at"], last["id"])
    items = [
        RunSummary(run_id=r["run_id"], topic=r["topic"], design=r["design"],
                   created_at=r["created_at"], slide_count=r["slide_count"],
                   caption=r["caption"] or "")
        for r in rows
    ]
    return ok(Page(items=items, next_cursor=next_cursor), request)


@router.get("/runs/{run_id}", response_model=Envelope[RenderOut],
            dependencies=[Depends(require_scope("read"))],
            summary="Fetch a previously rendered run")
@limiter.limit(LIGHT_LIMIT)
def v1_get_run(request: Request, run_id: str,
               topic: Optional[str] = Query(default=None, pattern=r"^[a-z0-9_]+$")):
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
    return ok(_to_render_out(result, base=_public_base(request)), request)


@router.get("/runs/{run_id}/export", summary="Download a run as a ZIP (binary)")
@limiter.limit(HEAVY_LIMIT)
def v1_export_run(request: Request, run_id: str,
                  topic: Optional[str] = Query(default=None, pattern=r"^[a-z0-9_]+$"),
                  _: ApiKeyInfo = Depends(require_scope("read"))):
    run_dir = _resolve_run_dir(run_id, topic)
    buf = _zip_stream(run_dir)
    return StreamingResponse(
        buf, media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{run_id}.zip"'},
    )


@router.delete("/runs/{run_id}", response_model=Envelope[dict],
               dependencies=[Depends(require_scope("write"))],
               summary="Delete a rendered run")
@limiter.limit(LIGHT_LIMIT)
def v1_delete_run(request: Request, run_id: str,
                  topic: Optional[str] = Query(default=None, pattern=r"^[a-z0-9_]+$")):
    existed = dedup.delete_run(run_id)
    try:
        run_dir = _resolve_run_dir(run_id, topic)
        shutil.rmtree(run_dir, ignore_errors=True)
        existed = True
    except HTTPException:
        pass
    if not existed:
        raise HTTPException(status_code=404, detail=f"run not found: {run_id}")
    return ok({"run_id": run_id, "deleted": True}, request)


# ── Async jobs ───────────────────────────────────────────────────────────────


def _job_to_out(job, *, base: str = "") -> JobOut:
    status_url = f"{base.rstrip('/')}/api/v1/jobs/{job.id}" if base else None
    return JobOut(
        job_id=job.id, kind=job.kind, status=job.status,
        created_at=int(job.created_at),
        started_at=int(job.started_at) if job.started_at else None,
        finished_at=int(job.finished_at) if job.finished_at else None,
        status_url=status_url, result=job.result, error=job.error,
    )


@router.post("/jobs", status_code=202, response_model=Envelope[JobOut],
             dependencies=[Depends(require_scope("write"))],
             summary="Submit an async render job")
@limiter.limit(HEAVY_LIMIT)
def v1_create_job(request: Request, body: JobRequest):
    """Enqueue a render → `202` + `job_id`. Poll `GET /api/v1/jobs/{job_id}` or
    supply an https `webhook_url` (SSRF-guarded) for a completion callback."""
    from api.server import (
        render_edit_impl,
        render_impl,
        render_partial_impl,
        _validate_topic_design,
    )
    base = _public_base(request)
    _validate_topic_design(body.topic, body.design)
    impls = {"render": render_impl, "render_edit": render_edit_impl,
             "render_partial": render_partial_impl}
    impl = impls[body.kind]

    def _fn():
        return impl(body, base=base)

    info = getattr(request.state, "api_key", None)
    job = get_store().submit(
        body.kind, _fn, api_key_name=getattr(info, "name", "-"),
        webhook_url=body.webhook_url or "", base=base,
    )
    return ok(_job_to_out(job, base=base), request)


@router.get("/jobs", response_model=Envelope[Page[JobOut]],
            dependencies=[Depends(require_scope("read"))],
            summary="List async jobs (cursor-paginated)")
@limiter.limit(LIGHT_LIMIT)
def v1_list_jobs(request: Request,
                 limit: int = Query(20, ge=1, le=100),
                 cursor: Optional[str] = Query(default=None)):
    base = _public_base(request)
    jobs = get_store().list()  # snapshot, newest first
    page_jobs, next_cursor = paginate_sorted(
        jobs, limit=limit, cursor=cursor, key=lambda j: (int(j.created_at), j.seq)
    )
    items = [_job_to_out(j, base=base) for j in page_jobs]
    return ok(Page(items=items, next_cursor=next_cursor), request)


@router.get("/jobs/{job_id}", response_model=Envelope[JobOut],
            dependencies=[Depends(require_scope("read"))],
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
    return ok(_job_to_out(job, base=_public_base(request)), request)


# ── API keys (admin) ─────────────────────────────────────────────────────────


@router.get("/api-keys", response_model=Envelope[list[ApiKeyOut]],
            dependencies=[Depends(require_scope("admin"))], summary="List API keys")
@limiter.limit(LIGHT_LIMIT)
def v1_list_keys(request: Request):
    return ok([ApiKeyOut(**k) for k in api_keys.list_keys()], request)


@router.post("/api-keys", status_code=201, response_model=Envelope[ApiKeyCreateOut],
             dependencies=[Depends(require_scope("admin"))],
             summary="Create an API key (raw secret shown once)")
@limiter.limit(LIGHT_LIMIT)
def v1_create_key(request: Request, body: ApiKeyCreateRequest):
    try:
        rec = api_keys.create_key(body.name, body.scopes)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return ok(ApiKeyCreateOut(**rec), request)


@router.get("/api-keys/{key_id}", response_model=Envelope[ApiKeyOut],
            dependencies=[Depends(require_scope("admin"))], summary="Get an API key")
@limiter.limit(LIGHT_LIMIT)
def v1_get_key(request: Request, key_id: str):
    rec = api_keys.get_key(key_id)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"key not found: {key_id}")
    return ok(ApiKeyOut(**rec), request)


@router.delete("/api-keys/{key_id}", response_model=Envelope[dict],
               dependencies=[Depends(require_scope("admin"))],
               summary="Revoke an API key")
@limiter.limit(LIGHT_LIMIT)
def v1_revoke_key(request: Request, key_id: str):
    if not api_keys.revoke_key(key_id):
        raise HTTPException(status_code=404,
                            detail=f"key not found or already revoked: {key_id}")
    return ok({"key_id": key_id, "revoked": True}, request)

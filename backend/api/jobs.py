"""In-process async job runner for the public /api/v1 API.

A full render takes 10–40 s (image fetch + verify dominate). Holding an HTTP
connection open that long is fragile behind a reverse proxy / Tailscale Funnel,
so the public API offers an async mode: submit a job, poll for status, and
optionally receive a webhook on completion.

This is deliberately IN-PROCESS — a `dict` guarded by a lock plus a small
`ThreadPoolExecutor` — not Redis/Celery: Carousel Studio runs as a single
uvicorn instance. The trade-off is that job state is **ephemeral**: it is lost
on restart/redeploy and evicted after a TTL. The durable handle is the
`run_id` — a finished run's slides + `run.json` persist on disk and can be
re-read via `GET /api/v1/runs/{run_id}`, even after the job is gone.
"""
from __future__ import annotations

import copy
import hashlib
import hmac
import ipaddress
import json
import os
import socket
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable, Optional
from urllib.parse import urlparse

from fastapi import HTTPException

from core import http
from core.log import get_logger

log = get_logger("api.jobs")

# Tailscale / CGNAT shared-address space. Python's `ipaddress.is_private`
# does not flag this range on every version, so we reject it explicitly —
# the app's deploy host sits on a tailnet (see DEPLOY.md).
_CGNAT = ipaddress.ip_network("100.64.0.0/10")


@dataclass
class Job:
    id: str
    kind: str
    status: str = "queued"  # queued | running | succeeded | failed
    created_at: float = 0.0
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    result: Optional[dict] = None  # serialized RenderOut on success
    error: Optional[dict] = None   # {code, message, details?} on failure
    api_key_name: str = "-"
    webhook_url: str = ""
    seq: int = 0  # monotonic insertion order — keyset tiebreaker for list()


def _truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes")


# ── webhook SSRF guard ──────────────────────────────────────────────────────


def is_safe_webhook_url(url: str) -> bool:
    """Validate a user-supplied webhook URL before the server POSTs to it.

    Requires `https://` (the API runs on a tailnet; a user-supplied URL is
    untrusted request data even from an authenticated caller). Reuses the
    app's SSRF gate (`core.http.is_public_url`, which rejects loopback /
    RFC1918 / link-local / multicast / reserved) and additionally rejects
    the CGNAT/Tailscale `100.64.0.0/10` range.

    Escape hatches for self-hosted receivers:
    - `CAROUSEL_WEBHOOK_ALLOW_HOSTS` — comma list of allowed hostnames.
    - `CAROUSEL_ALLOW_LOCAL=1` — dev opt-in that also relaxes http + locals.

    Limitation (best-effort): this validates the IPs the host resolves to NOW,
    but `requests` re-resolves the hostname at connect time, so a determined
    attacker who controls authoritative DNS with a low TTL could rebind to a
    private/loopback address between this check and the actual POST (a blind,
    authenticated SSRF — the response body is never returned to the caller).
    Delivery is gated behind a valid API key; for untrusted callers, constrain
    egress at the network layer and/or pin receivers via
    `CAROUSEL_WEBHOOK_ALLOW_HOSTS`.
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    host = parsed.hostname
    if not host:
        return False

    allow = {h.strip().lower() for h in
             os.environ.get("CAROUSEL_WEBHOOK_ALLOW_HOSTS", "").split(",") if h.strip()}
    if host.lower() in allow:
        return True

    if _truthy("CAROUSEL_ALLOW_LOCAL"):
        return True

    if parsed.scheme != "https":
        return False
    if not http.is_public_url(url):
        return False
    try:
        for info in socket.getaddrinfo(host, None):
            ip = ipaddress.ip_address(info[4][0])
            if ip.version == 4 and ip in _CGNAT:
                return False
    except socket.gaierror:
        return False
    return True


# ── job store ───────────────────────────────────────────────────────────────


class JobStore:
    """Thread-safe in-memory job registry backed by a worker pool.

    Every mutation (and the TTL eviction sweep) holds a single lock. The
    eviction sweep snapshots the keys first and deletes after, so it never
    mutates the dict mid-iteration.
    """

    def __init__(self, *, max_workers: int, ttl: float):
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._ttl = ttl
        self._seq = 0  # monotonic counter for keyset-pagination tiebreaker
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="carousel-job"
        )

    def submit(self, kind: str, fn: Callable[[], object], *,
               api_key_name: str = "-", webhook_url: str = "",
               base: str = "") -> Job:
        """Register a job and schedule `fn` on the worker pool. `fn` returns a
        serializable RenderOut-like object (has `.model_dump()`) or raises
        `HTTPException` for a pipeline failure. Returns a snapshot of the job
        in its `queued` state."""
        self._evict_expired()
        job = Job(id=uuid.uuid4().hex, kind=kind, created_at=time.time(),
                  api_key_name=api_key_name, webhook_url=webhook_url)
        # Snapshot the queued state under the lock BEFORE scheduling the worker,
        # otherwise an idle worker can advance the shared Job object past
        # "queued" before we copy it and the 202 body becomes non-deterministic.
        with self._lock:
            self._seq += 1
            job.seq = self._seq
            self._jobs[job.id] = job
            snap = copy.copy(job)
        self._executor.submit(self._run, job.id, fn, base)
        return snap

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            job = self._jobs.get(job_id)
            return copy.copy(job) if job is not None else None

    def list(self) -> list[Job]:
        """Snapshot of all jobs, newest first (by created_at, then seq)."""
        with self._lock:
            jobs = [copy.copy(j) for j in self._jobs.values()]
        jobs.sort(key=lambda j: (j.created_at, j.seq), reverse=True)
        return jobs

    def _set(self, job_id: str, **fields) -> Optional[Job]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            for k, v in fields.items():
                setattr(job, k, v)
            return copy.copy(job)

    def _run(self, job_id: str, fn: Callable[[], object], base: str) -> None:
        self._set(job_id, status="running", started_at=time.time())
        try:
            out = fn()
            result = out.model_dump() if hasattr(out, "model_dump") else out
            snap = self._set(job_id, status="succeeded", result=result,
                             finished_at=time.time())
        except HTTPException as exc:
            snap = self._set(job_id, status="failed",
                             error=_error_from_http(exc), finished_at=time.time())
        except Exception:  # never let a worker thread die silently
            # Log the full traceback server-side, but return a generic message
            # to the client/webhook — don't leak internals (paths, library
            # text), matching how the sync HTTPException/500 paths behave.
            log.exception("job %s crashed", job_id)
            snap = self._set(job_id, status="failed",
                             error={"code": "internal_error", "message": "internal error"},
                             finished_at=time.time())
        if snap is not None:
            _deliver_webhook(snap)

    def _evict_expired(self) -> None:
        # Lazy / submit-triggered: only called from submit(), never from get().
        # An expired-but-unswept finished job stays retrievable until the next
        # submission — fine for an ephemeral single-instance store (the TTL is
        # memory hygiene, not a correctness/security boundary).
        now = time.time()
        with self._lock:
            stale = [jid for jid, j in self._jobs.items()
                     if j.finished_at and (now - j.finished_at) > self._ttl]
            for jid in stale:
                del self._jobs[jid]

    def shutdown(self) -> None:
        # Single-instance: in-flight jobs are abandoned on shutdown. Consumers
        # re-submit or fall back to GET /runs/{run_id} once the run dir exists.
        self._executor.shutdown(wait=False, cancel_futures=True)


def _error_from_http(exc: HTTPException) -> dict:
    """Map an impl-layer HTTPException to a job error dict. Pipeline failures
    (409) carry the full result dict as `detail` with diagnostics."""
    detail = exc.detail
    if isinstance(detail, dict):
        return {
            "code": detail.get("status", "conflict"),
            "message": detail.get("message", "render failed"),
            "details": detail.get("diagnostics") or detail,
        }
    code_map = {400: "bad_request", 404: "not_found", 409: "conflict"}
    return {"code": code_map.get(exc.status_code, f"http_{exc.status_code}"),
            "message": str(detail)}


# ── webhook delivery ────────────────────────────────────────────────────────


def _deliver_webhook(job: Job) -> None:
    """Best-effort signed webhook POST on job completion (success OR failure).
    SSRF-guarded, https-only, 5 s timeout, no redirects, one retry."""
    if not job.webhook_url:
        return
    if not is_safe_webhook_url(job.webhook_url):
        log.warning("job %s: webhook_url rejected by SSRF guard: %s",
                    job.id, job.webhook_url)
        return
    payload = {
        "job_id": job.id,
        "kind": job.kind,
        "status": job.status,
        "result": job.result,
        "error": job.error,
        "finished_at": int(job.finished_at) if job.finished_at else None,
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "carousel-studio-webhook/1",
    }
    secret = os.environ.get("CAROUSEL_WEBHOOK_SECRET", "")
    if secret:
        sig = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        headers["X-Carousel-Signature"] = f"sha256={sig}"
    for attempt in range(2):  # 1 try + 1 retry
        try:
            resp = http.session().post(
                job.webhook_url, data=body, headers=headers,
                timeout=5, allow_redirects=False,
            )
            if resp.status_code < 400:
                return
            log.warning("job %s webhook %s → HTTP %s",
                        job.id, job.webhook_url, resp.status_code)
        except Exception as exc:
            log.warning("job %s webhook delivery failed: %s", job.id, exc)
        if attempt == 0:
            time.sleep(0.5)


# ── module-level singleton ──────────────────────────────────────────────────

_store: Optional[JobStore] = None
_store_lock = threading.Lock()


def get_store() -> JobStore:
    global _store
    if _store is not None:
        return _store
    with _store_lock:
        if _store is None:
            workers = int(os.environ.get("CAROUSEL_API_JOB_WORKERS", "2"))
            ttl = float(os.environ.get("CAROUSEL_API_JOB_TTL", "3600"))
            _store = JobStore(max_workers=max(1, workers), ttl=ttl)
    return _store


def shutdown_store() -> None:
    global _store
    with _store_lock:
        if _store is not None:
            _store.shutdown()
            _store = None

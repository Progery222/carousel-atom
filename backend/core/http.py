"""Shared HTTP client with sane retries, connection pooling, and a
parallel image downloader.

Why this module:
- Every parser used to create its own `requests.get(...)` — no connection
  reuse, no retries, no timeouts policy. We now share one Session with
  HTTPAdapter + urllib3 Retry across the whole app.
- Image downloads in `viral_roundup` were strictly sequential. Pulling
  5 hero images one after another costs ~3-5 s for nothing. We expose
  `download_images_parallel` that uses a small thread pool.
"""
from __future__ import annotations

import hashlib
import ipaddress
import os
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from core.log import get_logger
from core.parsers.base import HEADERS

log = get_logger("http")

_session: requests.Session | None = None
_session_lock = threading.Lock()


def session() -> requests.Session:
    """Return a process-wide Session with retries + keep-alive."""
    global _session
    if _session is not None:
        return _session
    with _session_lock:
        if _session is not None:
            return _session
        s = requests.Session()
        s.headers.update(HEADERS)
        retry = Retry(
            total=3,
            backoff_factor=0.7,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET", "HEAD"),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(
            max_retries=retry,
            pool_connections=20,
            pool_maxsize=20,
        )
        s.mount("http://", adapter)
        s.mount("https://", adapter)
        _session = s
        return s


def get(url: str, *, timeout: float = 15.0, **kw) -> requests.Response:
    """Convenience wrapper around the shared session.GET."""
    return session().get(url, timeout=timeout, **kw)


def post(url: str, *, timeout: float = 30.0, **kw) -> requests.Response:
    """POST through the shared session. Retry policy still applies for
    idempotent status codes (429/5xx) because we passed `allowed_methods`
    that explicitly excludes POST — so 5xx on POST surfaces as an error
    rather than silently double-submitting. For LLM chat completions
    this is what we want."""
    return session().post(url, timeout=timeout, **kw)


# ── SSRF guard ──────────────────────────────────────────────────────────────

# Trip wire for development: if you really want to point the studio at
# localhost (e.g. a local mock for image-search), opt in explicitly.
_ALLOW_LOCAL = os.environ.get("CAROUSEL_ALLOW_LOCAL", "").lower() in ("1", "true", "yes")


def is_public_url(url: str) -> bool:
    """Return True iff `url` resolves to a public, routable IP address.

    Rejects private (RFC1918), loopback, link-local, multicast and reserved
    ranges. This is the SSRF gate used before any HTTP fetch that takes a
    URL from user-controlled data (RSS items, image-search results,
    /upload-image responses). For dev there's an env opt-out
    `CAROUSEL_ALLOW_LOCAL=1`.
    """
    if not url:
        return False
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    host = parsed.hostname
    if not host:
        return False
    if _ALLOW_LOCAL:
        return True
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        log.warning("SSRF guard: DNS resolution failed for %s", host)
        return False
    for info in infos:
        ip_str = info[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            return False
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            return False
    return True


# ── cache cleanup ───────────────────────────────────────────────────────────


def prune_dir_older_than(directory: Path, days: int,
                          *, keep_names: set[str] | None = None) -> int:
    """Remove files in `directory` (recursively) whose mtime is older than
    `days` days. Returns the number of files deleted. Used to keep
    `_verify_cache/` and `data/output/<run_id>/` from growing forever.

    `keep_names` is an optional whitelist of top-level entry names that
    must be preserved regardless of age (used to keep posted runs that
    are still referenced from the dedup `posts` table).
    """
    if not directory.exists():
        return 0
    cutoff = time.time() - days * 86400
    deleted = 0
    keep = keep_names or set()
    for entry in directory.iterdir():
        if entry.name in keep:
            continue
        try:
            mtime = entry.stat().st_mtime
        except OSError:
            continue
        if mtime >= cutoff:
            continue
        try:
            if entry.is_dir():
                import shutil as _shutil
                _shutil.rmtree(entry, ignore_errors=True)
            else:
                entry.unlink(missing_ok=True)
            deleted += 1
        except OSError as e:
            log.debug("prune skip %s: %s", entry, e)
    return deleted


# ── image downloader ────────────────────────────────────────────────────────


# Width below which we *log* a warning but still keep the photo on screen —
# rendering a fuzzy hero is almost always better than a flat black bar.
SMALL_IMAGE_LOG_WIDTH = 600


def _download_one(url: str, save_dir: Path) -> str | None:
    if not url or not url.startswith("http"):
        return None
    if not is_public_url(url):
        log.warning("download: refusing non-public URL %s", url[:80])
        return None
    save_dir.mkdir(parents=True, exist_ok=True)
    name = hashlib.md5(url.encode()).hexdigest()[:12] + ".jpg"
    dst = save_dir / name
    if dst.exists() and dst.stat().st_size > 256:  # already cached
        return str(dst)
    try:
        resp = get(url, stream=True, timeout=20)
        resp.raise_for_status()
        with open(dst, "wb") as f:
            for chunk in resp.iter_content(8192):
                f.write(chunk)
        # Soft sanity check: keep the file but log small downloads so we
        # can see in logs which sources keep returning thumbs.
        try:
            from PIL import Image
            with Image.open(dst) as im:
                if im.width < SMALL_IMAGE_LOG_WIDTH:
                    log.info("small image (%dx%d) kept from %s",
                             im.width, im.height, url[:60])
        except Exception:
            # If we can't read it back, treat the download as a failure.
            try:
                dst.unlink(missing_ok=True)
            except Exception:
                pass
            return None
        return str(dst)
    except Exception as e:
        log.warning("image download failed (%s): %s", url[:60], e)
        try:
            dst.unlink(missing_ok=True)  # best-effort cleanup
        except Exception:
            pass
        return None


def download_images_parallel(urls: Iterable[str | None], save_dir: Path,
                             max_workers: int = 5) -> list[str | None]:
    """Download every URL, preserving input order. None inputs stay None."""
    items = list(urls)
    out: list[str | None] = [None] * len(items)
    indexed = [(i, u) for i, u in enumerate(items) if u]
    if not indexed:
        return out
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futs = {pool.submit(_download_one, u, save_dir): i for i, u in indexed}
        for fut in futs:
            idx = futs[fut]
            try:
                out[idx] = fut.result()
            except Exception as e:
                log.warning("image task crashed: %s", e)
                out[idx] = None
    return out

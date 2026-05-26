"""Background removal for hero photos.

Wraps `rembg` so designs (currently just `editorial_white`) can composite
cutout subjects onto coloured pages — the Threads-style "subject floating
on white" look.

The model download (first call) is ~170MB and takes 10-30s on a fresh
machine. Subsequent calls are 1-3s per photo on CPU, depending on size.
Results are cached on disk by source image content-hash so a repeat
render hits the cache instead of running inference twice.

Failures (model crash, RGB-only image, etc.) fall back to the original
photo path so the slide still renders, just without a cutout.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

from core.log import get_logger

log = get_logger("bg_remove")

# Lazy globals so the heavy rembg import only fires when someone actually
# requests a cutout (the rest of the pipeline shouldn't pay the cost).
_SESSION = None


def _session():
    """Cached rembg session. `u2netp` is the lightweight variant — 4MB
    download, fast, good enough for product/press photos. The full
    `u2net` (170MB) gives slightly cleaner edges but isn't worth the
    download on every fresh machine.
    """
    global _SESSION
    if _SESSION is None:
        # Local import keeps `import core.bg_remove` cheap when the
        # feature is unused.
        from rembg import new_session  # type: ignore
        _SESSION = new_session("u2netp")
    return _SESSION


def _cache_key(image_path: str) -> str:
    """Content-hash the source image so two articles with the same hero
    photo share a cutout."""
    h = hashlib.sha256()
    with open(image_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def cutout(image_path: str, cache_dir: Path) -> str:
    """Return a path to an RGBA PNG of the subject on transparent bg,
    or `image_path` itself if cutout fails.

    Cached by source-file content hash under `cache_dir`.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = _cache_key(image_path)
    out_path = cache_dir / f"{key}.png"
    if out_path.exists() and out_path.stat().st_size > 0:
        return str(out_path)

    try:
        from rembg import remove  # type: ignore
        with open(image_path, "rb") as f:
            src_bytes = f.read()
        cut_bytes = remove(src_bytes, session=_session())
        if not cut_bytes:
            log.warning("rembg returned empty for %s", image_path)
            return image_path
        with open(out_path, "wb") as f:
            f.write(cut_bytes)
        log.info("cutout cached → %s", out_path.name)
        return str(out_path)
    except Exception as e:
        log.warning("rembg failed for %s: %s", image_path, e)
        return image_path

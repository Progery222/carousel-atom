"""Centralised logger. Replaces scattered `print(...)` calls.

Usage:
    from core.log import get_logger
    log = get_logger(__name__)
    log.info("hello %s", name)

Level can be tweaked via env var CAROUSEL_LOG (default INFO).
"""
from __future__ import annotations

import logging
import os
import sys

_CONFIGURED = False


def _configure_root() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    level_name = os.environ.get("CAROUSEL_LOG", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(logging.Formatter(
        fmt="%(asctime)s %(levelname)-5s %(name)-22s | %(message)s",
        datefmt="%H:%M:%S",
    ))

    root = logging.getLogger("carousel")
    root.setLevel(level)
    root.handlers = [handler]
    root.propagate = False
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    _configure_root()
    if not name.startswith("carousel"):
        name = f"carousel.{name}"
    return logging.getLogger(name)

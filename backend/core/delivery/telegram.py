"""Telegram album delivery.

Reads bot token from `TELEGRAM_BOT_TOKEN` and per-topic chat from the
topic's `delivery.telegram_chat` field (which itself supports `env:VAR`
indirection — see `topic_loader._resolve_env`).

Sends slides as a media group (10-photo limit) and posts the long
caption as a follow-up text message so it doesn't get truncated.

The adapter is fully optional: if the env var or the topic chat is
missing, `is_configured(topic)` returns False and the pipeline simply
skips delivery.
"""
from __future__ import annotations

import contextlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import requests

from core.log import get_logger
from core.topic_loader import TopicConfig

log = get_logger("delivery.telegram")

TELEGRAM_API = "https://api.telegram.org"
PHOTO_LIMIT_PER_ALBUM = 10
MAX_PHOTO_CAPTION = 1024


@dataclass(frozen=True)
class DeliveryResult:
    ok: bool
    detail: str
    message_ids: list[int]


def is_configured(topic: TopicConfig) -> bool:
    return bool(os.environ.get("TELEGRAM_BOT_TOKEN")) and bool(topic.telegram_chat)


def _post(method: str, *, files=None, data=None) -> dict:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    url = f"{TELEGRAM_API}/bot{token}/{method}"
    resp = requests.post(url, files=files, data=data, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _send_album(chat_id: str, slide_paths: Iterable[str], caption: str | None) -> list[int]:
    paths = list(slide_paths)[:PHOTO_LIMIT_PER_ALBUM]
    if not paths:
        return []

    # ExitStack guarantees every successfully opened file is closed even
    # if an exception fires before we hit the request (e.g. in the media
    # list construction or json.dumps).
    with contextlib.ExitStack() as stack:
        files = {}
        media = []
        for i, p in enumerate(paths):
            key = f"photo_{i}"
            fh = stack.enter_context(open(p, "rb"))
            files[key] = (Path(p).name, fh, "image/png")
            item = {"type": "photo", "media": f"attach://{key}"}
            if i == 0 and caption:
                item["caption"] = caption[:MAX_PHOTO_CAPTION]
                item["parse_mode"] = "Markdown"
            media.append(item)

        data = {
            "chat_id": chat_id,
            "media": json.dumps(media),
        }
        result = _post("sendMediaGroup", files=files, data=data)
        return [m["message_id"] for m in result.get("result", [])]


def _send_text(chat_id: str, text: str) -> int | None:
    if not text.strip():
        return None
    result = _post("sendMessage", data={
        "chat_id": chat_id,
        "text": text[:4096],  # Telegram hard cap
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    })
    return result.get("result", {}).get("message_id")


def send(topic: TopicConfig, run_result: dict) -> DeliveryResult:
    """Push a finished run to the topic's Telegram chat."""
    if not is_configured(topic):
        return DeliveryResult(False, "telegram not configured", [])
    chat_id = topic.telegram_chat
    paths = run_result["slide_paths"]
    caption = run_result.get("caption", "")
    short_caption = f"*{topic.display_name}* · {len(paths)} slides"
    try:
        msg_ids = _send_album(chat_id, paths, caption=short_caption)
        # If caption is long, dump the full text as a separate message.
        if caption and len(caption) > MAX_PHOTO_CAPTION:
            text_id = _send_text(chat_id, caption)
            if text_id:
                msg_ids.append(text_id)
        log.info("delivered %d photos to %s", len(msg_ids), chat_id)
        return DeliveryResult(True, "ok", msg_ids)
    except Exception as e:
        log.warning("telegram delivery failed: %s", e)
        return DeliveryResult(False, str(e), [])


# Sentinel-style namespace so the adapter registry can refer to us by slug.
class _TelegramAdapter:
    slug = "telegram"
    name = "Telegram album"
    is_configured = staticmethod(is_configured)
    send = staticmethod(send)


telegram_adapter = _TelegramAdapter()

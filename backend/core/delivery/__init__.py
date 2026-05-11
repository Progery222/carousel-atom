"""Delivery adapters. Each module exposes `send(topic, run_result)` and a
`describe()` helper that returns whether the adapter is configured.

Adapters are intentionally independent — Telegram doesn't care about
TikTok upload mechanics, etc. The pipeline calls into one of them only
when explicitly asked via `run_once(..., deliver=...)`.
"""
from core.delivery.telegram import telegram_adapter

ADAPTERS = {
    telegram_adapter.slug: telegram_adapter,
}


def get_adapter(slug: str):
    if slug not in ADAPTERS:
        raise KeyError(f"Unknown delivery adapter '{slug}'. "
                       f"Available: {list(ADAPTERS)}")
    return ADAPTERS[slug]

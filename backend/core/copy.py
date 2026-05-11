"""Hook / CTA copy resolver.

Used to live as hard-coded f-strings inside `designs/viral_roundup.py`.
Now every topic.yaml may declare its own pools:

    hook_pool:
      viral:
        - badge: "BREAKING"
          line1: "{n} {label} STORIES"
          line2: "BLOWING UP"
          line3: "RIGHT NOW"
          sub1:  "From scandals to surprises —"
          sub2:  "you missed all of these"
          tease: "#1 WILL SHOCK YOU"
      severe:
        - badge: "DEVELOPING"
          line1: "{n} {label} STORIES"
          line2: "YOU NEED"
          line3: "TO SEE"
          sub1:  "All the major moves"
          sub2:  "from the last 24 hours"
          tease: ""

    cta_pool:
      viral:
        - q1: "WHICH STORY"
          q2: "SHOCKED YOU"
          q3: "THE MOST?"
          prompt1: "Drop the number"
          prompt2: "in the comments"
      severe:
        - q1: "WHICH STORY"
          q2: "STOOD OUT"
          q3: "TO YOU?"
          prompt1: "Share your thoughts"
          prompt2: "in the comments"

Topics without these blocks fall back to sensible defaults so existing
configs keep rendering identically.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from core.topic_loader import TopicConfig


@dataclass(frozen=True)
class HookCopy:
    badge: str
    line1: str
    line2: str
    line3: str
    sub1: str
    sub2: str
    tease: str


@dataclass(frozen=True)
class CtaCopy:
    q1: str
    q2: str
    q3: str
    prompt1: str
    prompt2: str


# ── Defaults ────────────────────────────────────────────────────────────────

_DEFAULT_HOOKS: dict[str, list[HookCopy]] = {
    "viral": [
        HookCopy("BREAKING",   "{n} {label} STORIES", "BLOWING UP",  "RIGHT NOW",
                 "From scandals to surprises —", "you missed all of these",
                 "#1 WILL SHOCK YOU"),
        HookCopy("BREAKING",   "{n} {label} HEADLINES", "EVERYONE",   "IS TALKING ABOUT",
                 "From rumours to results —", "this is the daily roundup",
                 "#1 IS WILD"),
        HookCopy("TODAY",      "{n} {label} STORIES",   "YOU CAN'T",  "MISS",
                 "All the action you missed —", "in 60 seconds",
                 "SAVE FOR LATER »"),
    ],
    "severe": [
        HookCopy("DEVELOPING", "{n} {label} STORIES", "YOU NEED",  "TO SEE",
                 "All the major moves",            "from the last 24 hours",
                 ""),
    ],
}

_DEFAULT_CTAS: dict[str, list[CtaCopy]] = {
    "viral": [
        CtaCopy("WHICH STORY", "SHOCKED YOU",  "THE MOST?",
                "Drop the number", "in the comments"),
        CtaCopy("WHICH ONE",   "GOT YOU",      "TALKING?",
                "Drop the number", "in the comments"),
        CtaCopy("WHICH STORY", "BLEW YOUR",    "MIND?",
                "Drop your pick",  "in the comments"),
    ],
    "severe": [
        CtaCopy("WHICH STORY", "STOOD OUT",    "TO YOU?",
                "Share your thoughts", "in the comments"),
    ],
}


# ── Public helpers ──────────────────────────────────────────────────────────


def hook_copy(topic: TopicConfig, *, tone: str = "viral", index: int | None = None) -> HookCopy:
    """Pick a hook for this topic. Tone falls back to 'viral' when missing."""
    pool = _resolve_pool(topic, "hook_pool", tone, _DEFAULT_HOOKS)
    return _pick(pool, index)


def cta_copy(topic: TopicConfig, *, tone: str = "viral", index: int | None = None) -> CtaCopy:
    pool = _resolve_pool(topic, "cta_pool", tone, _DEFAULT_CTAS)
    return _pick(pool, index)


def story_count_label(topic: TopicConfig) -> str:
    """Word that goes after the count, e.g. '5 NBA STORIES'.

    Strips the noisy "DAILY"/"NEWS" suffixes that come from display_name.
    """
    raw = topic.display_name.upper()
    for suf in (" DAILY", " NEWS", " UPDATE", " TODAY"):
        if raw.endswith(suf):
            raw = raw[: -len(suf)]
    return raw.strip() or topic.slug.upper()


# ── Internals ───────────────────────────────────────────────────────────────


def _resolve_pool(topic: TopicConfig, attr: str, tone: str, defaults: dict) -> list:
    custom = getattr(topic, attr, None) or {}
    pool = custom.get(tone) or custom.get("viral") or []
    if not pool:
        pool = defaults.get(tone) or defaults["viral"]
    return pool


def _pick(pool, index):
    if not pool:
        raise ValueError("empty copy pool")
    if index is None:
        return random.choice(pool)
    return pool[index % len(pool)]

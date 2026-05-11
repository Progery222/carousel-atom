"""Caption generator.

Used to be a single fixed template. Now it:
  - cleans up SEO-style title noise via `core.text.clean_headline`
  - mixes static topic hashtags with 1-3 dynamic "trending" hashtags
    derived from the actual articles in the carousel
  - exposes an optional LLM rewrite hook (gated by `topic.caption.llm_rewrite`)

The engine still works fully offline — no LLM call is required.
"""
from __future__ import annotations

from typing import Callable

from core.parsers.base import Article
from core.text import clean_headline, extract_trending_terms, hashtagify
from core.topic_loader import TopicConfig

# Optional LLM hook. Plug in via `set_llm_rewriter` so the package itself
# stays free of any LLM SDK dependency.
_LLM_REWRITER: Callable[[str], str] | None = None


def set_llm_rewriter(fn: Callable[[str], str] | None) -> None:
    """Wire up an external function (raw caption text → rewritten text).

    Studio can leave this unset to keep generation fully local. When set,
    captions for topics with `caption.llm_rewrite: true` will be passed
    through this function before returning.
    """
    global _LLM_REWRITER
    _LLM_REWRITER = fn


def _trim(s: str, n: int) -> str:
    s = s.strip()
    if len(s) <= n:
        return s
    return s[:n].rsplit(" ", 1)[0] + "…"


def _all_hashtags(topic: TopicConfig, articles: list[Article]) -> list[str]:
    static_tags = [f"#{t.lstrip('#')}" for t in (topic.caption.hashtags or [])]
    titles = [a.title for a in articles]
    dynamic = [hashtagify(t) for t in extract_trending_terms(titles, top_k=3)]
    seen: set[str] = set()
    merged: list[str] = []
    for tag in dynamic + static_tags:  # dynamic first → they show up early
        low = tag.lower()
        if low in seen or low == "#":
            continue
        seen.add(low)
        merged.append(tag)
    return merged


def render_caption(topic: TopicConfig, articles: list[Article]) -> str:
    intro = topic.caption.intro
    style = topic.caption.style

    cleaned: list[Article] = []
    for a in articles:
        a.title = clean_headline(a.title)
        cleaned.append(a)

    lines: list[str] = [intro, ""]

    if style == "bullet":
        for a in cleaned:
            lines.append(f"▪ {a.title}")
            if a.description:
                lines.append(_trim(a.description, 160))
            lines.append("")
    elif style == "thread":
        for i, a in enumerate(cleaned, 1):
            lines.append(f"{i}/ {a.title}")
            lines.append("")
    else:  # "hook+list"
        if cleaned:
            lines.append(cleaned[0].title.upper())
            lines.append("")
            lines.append("Today's stories:")
            for a in cleaned[1:]:
                lines.append(f"• {a.title}")
            lines.append("")

    tags = _all_hashtags(topic, cleaned)
    if tags:
        lines.append(" ".join(tags))

    text = "\n".join(lines).strip()

    if topic.caption.llm_rewrite and _LLM_REWRITER is not None:
        try:
            rewritten = _LLM_REWRITER(text)
            if rewritten and rewritten.strip():
                return rewritten.strip()
        except Exception:  # never fail the carousel because of an LLM hiccup
            pass
    return text


def render_telegram_caption(topic: TopicConfig, articles: list[Article]) -> str:
    """Short caption attached to the album itself, not the standalone TikTok caption."""
    head = f"*{topic.display_name}*\n\n"
    body = "\n".join(f"{i}. {clean_headline(a.title)}"
                     for i, a in enumerate(articles, 1))
    return head + body + "\n\n👉 Swipe for details!"

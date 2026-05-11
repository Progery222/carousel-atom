"""Optional LLM rewriter.

Anything OpenAI-compatible works (OpenAI itself, Anthropic via a proxy,
Groq, Ollama with `/v1` endpoint, etc.). Configuration is purely env
based so the rest of the codebase has no LLM dependency:

    LLM_BASE_URL   default "https://api.openai.com/v1"
    LLM_API_KEY    required to enable
    LLM_MODEL      default "gpt-4o-mini"

Wiring (call once on app startup, e.g. from api/server.py):

    from core import llm
    from core.caption_engine import set_llm_rewriter
    set_llm_rewriter(llm.caption_rewriter())

Each topic decides whether to actually use it via
`caption.llm_rewrite: true` in topic.yaml.
"""
from __future__ import annotations

import os
from typing import Callable

from core import http as http_client
from core.log import get_logger

log = get_logger("llm")

# User-supplied text is wrapped in <caption>…</caption> / <headline>…</headline>
# blocks so the model can tell instruction from data. We never use .format()
# on user input — that path interprets `{...}` and lets a malicious headline
# break out of its slot.
DEFAULT_PROMPT_HEAD = (
    "Rewrite the following social-media caption so it reads punchier and "
    "more engaging on TikTok and Instagram, while keeping the facts and the "
    "hashtags intact. Keep emoji and structure. Limit to 800 characters.\n\n"
    "ORIGINAL:\n<caption>\n"
)
DEFAULT_PROMPT_TAIL = "\n</caption>\n\nREWRITTEN:"

HEADLINE_PROMPT_HEAD = (
    "Rewrite this news headline in the punchy, all-caps TikTok/Instagram "
    "carousel style of the @f1newsflash account. Rules:\n"
    "- 7 to 12 words, never longer\n"
    "- present tense, active voice\n"
    "- preserve the names and the key fact\n"
    "- drop SEO filler ('after a thrilling 90 minutes', 'according to reports')\n"
    "- no clickbait phrasing ('you won't believe…', 'shock')\n"
    "- return ONLY the rewritten headline, no quotes, no explanation\n\n"
    "ORIGINAL: <headline>"
)
HEADLINE_PROMPT_TAIL = "</headline>\nREWRITTEN:"


# Per-style HEAD/TAIL pairs used by the studio's manual rewrite buttons.
# Keeping them here (instead of in api/server.py) means user input never
# meets `.format()` — the user text is concatenated between HEAD and TAIL
# verbatim, then sanitized to neutralize closing-tag breakouts.
HEADLINE_STYLES: dict[str, tuple[str, str]] = {
    "punchier": (
        "Rewrite this news headline to be punchier and tighter for a "
        "TikTok carousel. Same meaning, no extra words. Match the "
        "@f1newsflash voice — direct, present tense, no clickbait.\n\n"
        "Headline: <headline>",
        "</headline>",
    ),
    "factual": (
        "Rewrite this news headline as a sober, factual statement of "
        "what happened. Drop hype words. Keep it under 90 characters.\n\n"
        "Headline: <headline>",
        "</headline>",
    ),
    "hook": (
        "Rewrite this news headline so it ends on a hook that makes you "
        "want to read the next slide. Same facts, but front-load curiosity. "
        "Under 90 characters.\n\n"
        "Headline: <headline>",
        "</headline>",
    ),
    "translate_ru": (
        "Translate this news headline to Russian. Keep the punchy, "
        "tabloid-headline voice — short, present tense.\n\n"
        "Headline: <headline>",
        "</headline>",
    ),
}


def _is_enabled() -> bool:
    return bool(os.environ.get("LLM_API_KEY"))


def _sanitize_user_text(text: str) -> str:
    """Strip closing delimiter tags that a malicious headline could use to
    pretend it's exiting the user-data block."""
    return text.replace("</caption>", "").replace("</headline>", "")


def _post_chat(messages: list[dict], *, max_tokens: int = 700,
               temperature: float = 0.7) -> str | None:
    """Single point of contact with the chat-completions endpoint.
    Returns the model's text reply or None on any failure. Uses the
    shared retry-session (`core.http`) so 429/5xx are retried with
    backoff instead of failing on the first hiccup."""
    base = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = os.environ.get("LLM_MODEL", "gpt-4o-mini")
    key = os.environ.get("LLM_API_KEY", "")
    if not key:
        return None
    try:
        resp = http_client.post(
            f"{base}/chat/completions",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        log.warning("LLM call failed: %s", e)
        return None


def caption_rewriter() -> Callable[[str], str] | None:
    """Return a function `text -> text` or None if no API key is configured."""
    if not _is_enabled():
        return None

    def _rewrite(caption: str) -> str:
        if not caption.strip():
            return caption
        safe = _sanitize_user_text(caption)
        text = _post_chat(
            [
                {"role": "system",
                 "content": "You polish news-roundup captions for short-form video."},
                {"role": "user",
                 "content": DEFAULT_PROMPT_HEAD + safe + DEFAULT_PROMPT_TAIL},
            ],
            max_tokens=700,
        )
        return text or caption

    return _rewrite


def headline_rewriter(style: str | None = None) -> Callable[[str], str] | None:
    """Return a function `headline -> rewritten_headline` or None if no
    API key is configured. Used by the pipeline when a topic opts in via
    `caption.llm_rewrite_titles: true`. Each call costs ~50 tokens, so
    a 5-slide carousel is roughly 250 tokens of LLM work — pennies on
    GPT-4o-mini, fractions of a cent on Groq/Ollama.

    `style` picks a HEAD/TAIL pair from `HEADLINE_STYLES` (used by the
    studio's manual rewrite buttons). None falls back to the default
    @f1newsflash all-caps prompt.
    """
    if not _is_enabled():
        return None

    head, tail = HEADLINE_STYLES.get(style or "", (HEADLINE_PROMPT_HEAD, HEADLINE_PROMPT_TAIL))

    def _rewrite(title: str) -> str:
        if not title.strip():
            return title
        safe = _sanitize_user_text(title)
        text = _post_chat(
            [
                {"role": "system",
                 "content": "You rewrite news headlines for TikTok carousels. "
                            "Match the punchy, all-caps voice of @f1newsflash."},
                {"role": "user",
                 "content": head + safe + tail},
            ],
            max_tokens=80, temperature=0.55,
        )
        if not text:
            return title
        # Strip surrounding quotes the model sometimes adds despite the prompt.
        text = text.strip().strip('"').strip("'").rstrip(".")
        # Sanity: if the model spat out something dramatically different
        # in length (5x longer than original), fall back to the original.
        if len(text) > len(title) * 3 + 30:
            return title
        return text

    return _rewrite

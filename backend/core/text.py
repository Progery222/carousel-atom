"""Headline / description text helpers.

Two responsibilities:
  - `clean_headline` — strip publisher noise, fix trailing punctuation,
    collapse whitespace, deal with a few common SEO-spam patterns.
  - `extract_trending_terms` — surface proper-noun-ish terms from a batch of
    article titles. Used by the caption engine to add 1-2 dynamic hashtags
    on top of the static topic ones.

Both are deliberately rule-based so they work offline. An optional LLM
rewrite hook is wired up in `caption_engine` and gated by the topic's
`caption.llm_rewrite` flag, so any future LLM provider can plug in.
"""
from __future__ import annotations

import html
import re
from collections import Counter
from typing import Iterable

# Words that should never become hashtags or "trending terms".
_STOP = frozenset({
    "the", "and", "for", "with", "from", "into", "after", "before", "over",
    "this", "that", "these", "those", "their", "they", "them", "his", "her",
    "him", "she", "you", "your", "our", "we", "us", "but", "not", "are",
    "was", "were", "is", "be", "been", "being", "have", "has", "had", "will",
    "would", "could", "should", "can", "may", "might", "must", "do", "does",
    "did", "say", "says", "said", "tell", "tells", "told", "get", "gets",
    "got", "gone", "go", "goes", "now", "today", "yesterday", "tomorrow",
    "more", "less", "most", "least", "first", "last", "next", "previous",
    "best", "worst", "biggest", "smallest", "new", "old", "year", "years",
    "week", "weeks", "month", "months", "day", "days", "hour", "hours",
    "vs", "vs.", "off", "out", "in", "on", "at", "to", "of", "by", "as",
})


_PUBLISHER_TAIL = re.compile(
    r"\s*(?:[\|\-–—•·:]\s*)(?:"
    r"ESPN|Bleacher Report|The Athletic|HoopsHype|"
    r"NBA(?:\.com)?|NHL(?:\.com)?|MLB(?:\.com)?|"
    r"Formula\s*1®?|F1\.com|autosport|Autosport|Motorsport\.com|"
    r"MMA\s*Fighting|MMA\s*Junkie|TMZ|GQ|Forbes|"
    r"Goal\.com|Goal|BBC\s*Sport"
    r")\s*$",
    re.IGNORECASE,
)

_MULTI_PUNCT = re.compile(r"([!?.,])\1+")
_TRAILING_DOTS = re.compile(r"\s*\.\s*\.\s*\.\s*$")


def clean_headline(title: str) -> str:
    """Best-effort sanitisation. Idempotent — safe to call multiple times."""
    if not title:
        return title
    t = html.unescape(title)
    t = _PUBLISHER_TAIL.sub("", t)
    t = _MULTI_PUNCT.sub(r"\1", t)
    t = _TRAILING_DOTS.sub("…", t)
    t = re.sub(r"\s+", " ", t).strip(" -|·•")
    return t


_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9'’\-]+")


def extract_trending_terms(titles: Iterable[str], *, top_k: int = 3,
                           min_count: int = 2) -> list[str]:
    """Return up to `top_k` capitalised tokens that recur across titles.

    Heuristic — captures multi-word brands by counting bigrams that look
    like proper nouns (both tokens capitalised). Falls back to single-word
    proper nouns when bigrams don't repeat.
    """
    bigram_counts: Counter[str] = Counter()
    word_counts: Counter[str] = Counter()
    for raw in titles:
        words = _TOKEN_RE.findall(raw or "")
        # Bigrams of capitalised words → "Lewis Hamilton", "LeBron James".
        for w1, w2 in zip(words, words[1:]):
            if w1[:1].isupper() and w2[:1].isupper() \
                    and w1.lower() not in _STOP and w2.lower() not in _STOP:
                bigram_counts[f"{w1} {w2}"] += 1
        for w in words:
            if w[:1].isupper() and w.lower() not in _STOP and len(w) > 2:
                word_counts[w] += 1

    out: list[str] = []
    for term, c in bigram_counts.most_common():
        if c >= min_count and len(out) < top_k:
            out.append(term)
    if len(out) < top_k:
        for term, c in word_counts.most_common():
            # Skip words already covered by a chosen bigram.
            if any(term in b for b in out):
                continue
            if c >= min_count and len(out) < top_k:
                out.append(term)
    return out


def hashtagify(term: str) -> str:
    return "#" + re.sub(r"[^A-Za-z0-9]", "", term).lower()


# Marketing / nav-bar fluff publishers leak into og:description. We
# strip these phrases before the slide engine sees them. Each pattern
# is anchored to a punctuation boundary so we don't accidentally eat
# legitimate content (e.g. "Click here to read more about Mudryk" is
# 100% fluff that would leave us with nothing — we only strip fluff
# when there's other content first).
_DESC_FLUFF_PATTERNS = (
    re.compile(r"^By\s+[\w\s.]+\s+[-–—]\s+", re.IGNORECASE),    # leading byline
    re.compile(r"^IMAGE:\s*[^.]+\.\s*", re.IGNORECASE),         # leading "IMAGE:" caption
    re.compile(r"^The Athletic\s*[-–—]\s*", re.IGNORECASE),     # publisher prefix
    # Trailing CTA noise — only strip when there's a sentence-ending
    # punctuation immediately before, so we don't truncate live content.
    re.compile(r"[.!?]\s+(?:click here|read more|subscribe now|download the app|sign up for our)\b.*$",
               re.IGNORECASE),
    # "The post X appeared first on Y" tail that WordPress feeds emit.
    re.compile(r"\s*The\s+post\s+.+?\s+appeared\s+first\s+on\b.*$", re.IGNORECASE),
    # "Continue reading" / "Read more" links that some feeds append.
    re.compile(r"\s+(?:Continue reading|Read more|Read full article)\b.*$", re.IGNORECASE),
)

# RSS descriptions arrive with HTML noise — wrapping <p>/<div>, leading
# <img> blocks, anchor "more-link" tails. Strip tags + decode entities
# before any other cleanup so the body doesn't render as literal markup.
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_HTML_BLOCK_RE = re.compile(r"<(script|style|figure|figcaption|aside)[^>]*>.*?</\1>",
                             re.IGNORECASE | re.DOTALL)


def _strip_html(text: str) -> str:
    if not text:
        return ""
    text = _HTML_BLOCK_RE.sub(" ", text)
    text = _HTML_TAG_RE.sub(" ", text)
    # RSS feeds get truncated mid-tag by the upstream [:500] cap, leaving
    # an unclosed `<a href="…` at the end. Drop any trailing `<…` that
    # never reached a closing `>`.
    text = re.sub(r"<[^<>]*$", "", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()

# Permissive sentence-split: any word char (incl. lowercase brand prefixes
# like "iOS", "iPhone", "x86") can follow the punctuation. Avoids the
# old regex's failure where "Apple Notes is great. iOS 27 is better."
# read as one sentence because of the lowercase 'i'.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[\w\"'“(])")


def lead_fact(raw: str, *, max_chars: int = 130) -> str:
    """Pull a single tight 'fact line' out of the article description.

    Designs use this instead of `clean_description` when they want a
    one-line news kicker (the carousel-news look) rather than a multi-
    line paragraph (which reads like an article excerpt). Strategy:

      1. Strip HTML + leading/trailing fluff.
      2. Split into sentences. Pick the first sentence whose length is
         in a sweet spot (35..max_chars). Skip stub leads like
         "By John Smith." or "Photo: Reuters" — too short to carry the
         news.
      3. If no sentence fits, hard-trim with ellipsis at a word break.

    Returns "" when the source has nothing usable.
    """
    if not raw:
        return ""
    text = _strip_html(raw)
    for pat in _DESC_FLUFF_PATTERNS:
        text = pat.sub("", text)
    text = re.sub(r"\s+", " ", text).strip(" -|·")
    if not text:
        return ""

    sentences = _SENTENCE_SPLIT_RE.split(text)
    for s in sentences:
        s = s.strip()
        if not s:
            continue
        if 35 <= len(s) <= max_chars:
            return s
    # No sentence in the sweet spot. Take the first sentence and trim
    # at a word boundary if it's too long.
    first = sentences[0].strip() if sentences else ""
    if not first:
        return ""
    if len(first) <= max_chars:
        return first
    return first[:max_chars].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def clean_description(raw: str, *, max_chars: int = 220) -> str:
    """Sentence-aware cleanup for the body summary that designs render.

    Removes byline / marketing fluff, truncates at sentence boundaries
    where possible, and falls back to word boundaries otherwise. The
    output is meant to read as a self-contained 1-2 sentence factual
    summary on the slide.
    """
    if not raw:
        return ""
    text = _strip_html(raw)
    for pat in _DESC_FLUFF_PATTERNS:
        text = pat.sub("", text)
    text = re.sub(r"\s+", " ", text).strip(" -|·")

    if len(text) <= max_chars:
        # Avoid mid-sentence abrupt endings — common when an upstream
        # cap (e.g. RSS [:2000]) sliced the raw text before we got it.
        # If the text doesn't end on a sentence terminator, trim back to
        # the last one. If there is none, leave the text as-is (better
        # than returning empty).
        if not re.search(r"[.!?…”\"']\s*$", text):
            cut = max(text.rfind("."), text.rfind("!"), text.rfind("?"))
            if cut >= len(text) * 0.5:
                return text[: cut + 1]
        return text

    # Pick as many full sentences as fit under max_chars.
    sentences = _SENTENCE_SPLIT_RE.split(text)
    out = ""
    for s in sentences:
        if len(out) + len(s) + 1 > max_chars:
            break
        out = (out + " " + s).strip() if out else s
    if out and len(out) >= max_chars * 0.5:
        return out

    # Fallback: hard word-boundary trim with ellipsis.
    return text[:max_chars].rsplit(" ", 1)[0].rstrip(",;:") + "…"


# ── Single-headline entity extraction ───────────────────────────────────────


# Words that look like names but rarely help an image search ("World Cup"
# alone returns junk; "Lionel Messi" or "Ferrari" are great queries).
_QUERY_STOP = frozenset({
    "the", "a", "an", "for", "with", "from", "after", "into", "over",
    "about", "and", "or", "but", "as", "is", "was", "are", "were", "to",
    "of", "in", "on", "at", "by", "this", "that", "his", "her", "their",
    "they", "them", "you", "your", "could", "might", "expected", "set",
    "considering", "says", "claims", "reports", "told", "according",
    "breaking", "report", "exclusive", "today", "yesterday", "tomorrow",
    "new", "old", "best", "worst", "first", "last", "year", "years",
    "week", "month", "day", "stories", "story",
})


def extract_entities(title: str, *, max_terms: int = 5) -> list[str]:
    """Pull candidate "search queries" out of an article title.

    Returns the multi-word proper-noun phrases first (best for an image
    search — "Lionel Messi" beats "Messi" + "Lionel" individually), then
    standalone proper nouns, deduped and ordered by likely usefulness.

    Heuristic only — runs offline, no external service. Designed to feed
    `core.image_search.find_replacement_image`.
    """
    if not title:
        return []
    words = _TOKEN_RE.findall(title)
    bigrams: list[str] = []
    trigrams: list[str] = []

    def cap_ok(w: str) -> bool:
        return (
            w[:1].isupper() and len(w) > 1 and w.lower() not in _QUERY_STOP
        )

    for i in range(len(words) - 1):
        a, b = words[i], words[i + 1]
        if cap_ok(a) and cap_ok(b):
            bigrams.append(f"{a} {b}")
            if i < len(words) - 2 and cap_ok(words[i + 2]):
                trigrams.append(f"{a} {b} {words[i + 2]}")

    singles = [w for w in words if cap_ok(w) and len(w) > 3]

    seen: set[str] = set()
    out: list[str] = []
    for term in trigrams + bigrams + singles:
        key = term.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(term)
        if len(out) >= max_terms:
            break
    return out


# ── Aggressive "TikTok voice" rewriter ──────────────────────────────────────


# Trailing clauses that pad SEO headlines but kill tempo on a slide.
# Anything from these conjunctions to the end of the line gets dropped.
_TRAILING_CLAUSE_RE = re.compile(
    r",?\s+("
    r"after\s+(?:a\s+|the\s+|his\s+|her\s+|their\s+)?\w+"
    r"(?:\s+\w+){0,4}"
    r"|according\s+to\s+.+"
    r"|amid\s+.+"
    r"|despite\s+.+"
    r"|as\s+\w+\s+(?:reveals|admits|confirms|denies|warns|explains|says)\b.*"
    r"|while\s+.+"
    r"|for\s+the\s+(?:first|second|third|fourth|fifth)\s+time\b.*"
    r"|in\s+(?:season|year|race|qualifying)\b.*"
    r"|over\s+\w+\s+\w+\b.*"
    r")$",
    re.IGNORECASE,
)

# Common SEO-isms shortened to their tabloid equivalents.
_SHORTENINGS = (
    (re.compile(r"\bFormula\s*One\b",       re.IGNORECASE), "F1"),
    (re.compile(r"\bFormula\s*1\b",         re.IGNORECASE), "F1"),
    (re.compile(r"\bGrand\s+Prix\b",        re.IGNORECASE), "GP"),
    (re.compile(r"\bsaid\s+that\b",         re.IGNORECASE), "says"),
    (re.compile(r"\bwill\s+not\b",          re.IGNORECASE), "won't"),
    (re.compile(r"\bdo\s+not\b",            re.IGNORECASE), "don't"),
    (re.compile(r"\bdoes\s+not\b",          re.IGNORECASE), "doesn't"),
    (re.compile(r"\bhas\s+not\b",           re.IGNORECASE), "hasn't"),
    (re.compile(r"\bcannot\b",              re.IGNORECASE), "can't"),
    (re.compile(r"\bbecause\s+of\b",        re.IGNORECASE), "due to"),
    (re.compile(r"\bin\s+order\s+to\b",     re.IGNORECASE), "to"),
)

# Filler words at the very start that don't add information.
_LEADING_NOISE_RE = re.compile(
    r"^(?:report\s*[-:|]?\s*|breaking\s*[-:|]?\s*|exclusive\s*[-:|]?\s*|just in\s*[-:|]?\s*)",
    re.IGNORECASE,
)


def punchy(title: str, *, max_words: int = 14) -> str:
    """Aggressive rewrite into "TikTok newsflash voice".

    Transformations:
      - clean publisher tail (via clean_headline)
      - drop SEO trailing clauses (after… / according to… / amid… / etc.)
      - shorten verbose phrasings (Formula 1 → F1, will not → won't)
      - strip leading "REPORT:", "BREAKING:" markers (the slide already
        carries that signal via the topic emblem)
      - cap to `max_words` — anything past that gets a word-boundary trim

    Idempotent. Safe to call multiple times.
    """
    t = clean_headline(title or "")
    if not t:
        return t
    t = _LEADING_NOISE_RE.sub("", t)
    t = _TRAILING_CLAUSE_RE.sub("", t)
    for pat, repl in _SHORTENINGS:
        t = pat.sub(repl, t)
    t = re.sub(r"\s+", " ", t).strip(" -|·,")

    words = t.split()
    if len(words) > max_words:
        t = " ".join(words[:max_words]).rstrip(",;:") + "…"
    return t


# Stop-words used by `accent_phrase` — function words and bland verbs that
# shouldn't be the highlighted action of a headline.
_ACCENT_STOP = frozenset({
    "the", "a", "an", "is", "in", "on", "at", "to", "for", "of",
    "and", "or", "but", "with", "from", "by", "as", "it", "its",
    "has", "had", "have", "are", "was", "were", "will", "all",
    "how", "what", "when", "who", "why", "that", "this", "than",
    "now", "just", "even", "still", "so", "be", "been", "do", "does",
    "after", "before", "over", "into", "out", "up", "down",
    "his", "her", "their", "they", "them", "you", "your",
})


# Patterns that surface the "action verb" of a tabloid headline. Each
# pattern captures the word(s) we want highlighted in the slide accent.
# Inspired by @f1newsflash: the punch is usually the verb-after-modal
# ("considering RETIRING", "set to RETURN") or the verb+object pair
# ("STOP COMPLAINING", "SIGN VERSTAPPEN").
# Order matters: more specific patterns first. The first one that matches
# wins, so "X to SIGN VERSTAPPEN" (verb + object at end of clause) beats
# the more permissive "could VERB".
_ACCENT_TRIGGERS = (
    # 1) "X to VERB OBJECT$" — clause-final verb + object.
    re.compile(r"\bto\s+(\w+)\s+(\w+)\s*$", re.IGNORECASE),
    # 2) Negation pair (NEED, NOT, REJECTS) — both red.
    re.compile(
        r"\b(?:doesn['’]?t|don['’]?t|won['’]?t|can['’]?t|isn['’]?t|"
        r"denies|rejects|refuses|rules\s+out)\s+(\w+)",
        re.IGNORECASE,
    ),
    # 3) Quote / says / claims + 1-2 words.
    re.compile(
        r"\b(?:says?|claims?|admits|told|reveals?|warns?|fears?)\s+"
        r"(?:everyone\s+can\s+|that\s+)?"
        r"(\w+(?:\s+\w+)?)",
        re.IGNORECASE,
    ),
    # 4) Considering/expected/set + verb (single word after).
    re.compile(
        r"\b(?:considering|signing|chasing|targeting|leaving|quitting|"
        r"joining|expected\s+to|set\s+to|wants\s+to|plans\s+to|"
        r"about\s+to|going\s+to)\s+(\w+ING|\w+ED|\w+)\b",
        re.IGNORECASE,
    ),
    # 5) "based on X".
    re.compile(r"\bbased\s+on\s+(\w+(?:['’]s)?(?:\s+\w+)?)", re.IGNORECASE),
    # 6) Common standalone verb+noun pairs.
    re.compile(
        r"\b(STOP|RETURN|RETIRE|JOIN|QUIT|LEAVE|SCRAP|SIGN|END|BAN|BLOCK)\s+(\w+)",
        re.IGNORECASE,
    ),
    # 7) Bare modal + verb — last resort.
    re.compile(r"\b(?:could|might|will|may)\s+(\w+)\b", re.IGNORECASE),
)


def accent_phrase(title: str) -> set[str]:
    """Pick 1-2 words to highlight in the slide accent colour.

    Strategy mirrors @f1newsflash:
      1. Look for an "action trigger" (modal + verb, negation, says+phrase,
         to+verb+object…) — if found, highlight the captured words.
      2. Otherwise fall back to the last 1-2 significant words.
      3. Always keep at least one white word — never highlight the entire
         headline.

    Returns a set of UPPERCASE word strings (without trailing punctuation)
    so callers can do an O(1) "is this word an accent?" lookup.
    """
    if not title:
        return set()
    raw = title
    upper_words = [w.strip(",.!?\"'():;-").upper() for w in raw.split()]
    significant = [w for w in upper_words
                   if w and w.lower() not in _ACCENT_STOP and len(w) > 1]
    if not significant:
        return set()

    # Try trigger patterns in order — first hit wins.
    accent: set[str] = set()
    for pat in _ACCENT_TRIGGERS:
        m = pat.search(raw)
        if not m:
            continue
        groups = [g for g in m.groups() if g]
        for g in groups:
            for tok in g.upper().split():
                clean = tok.strip(",.!?\"'():;-")
                if clean and clean.lower() not in _ACCENT_STOP and len(clean) > 1:
                    accent.add(clean)
        if accent:
            break

    if not accent:
        accent = set(significant[-2:]) if len(significant) >= 2 else set(significant[-1:])

    # Safety: never highlight the whole title — keep at least one white word.
    if len(accent) >= len(significant):
        accent = set(significant[-1:])
    return accent

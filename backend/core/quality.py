"""Quality gates and scoring for articles before they hit the slide engine.

Two responsibilities:
  1. Hard filters: drop articles that would produce ugly slides or are
     clearly non-news (quizzes, polls, opinion, watch/video promos,
     on-this-day nostalgia, viewing guides, listicle fluff).
  2. Soft scoring: rank survivors so the carousel picks the most
     "share-able" ones, not just whatever was first in the feed.

Severity gate is intentionally light: tragic / harm-related items are
flagged so the design layer can drop the goofy "WILL SHOCK YOU" copy and
fall back to a neutral template. They still appear in the carousel.

The carousels are billed as factual breaking news. Anything that's clearly
engagement/filler from the source site is dropped here.
"""
from __future__ import annotations

import re
import time
from collections import defaultdict
from urllib.parse import urlparse

from core.parsers.base import Article


# Title patterns that signal NON-news content. Conservative — only obvious
# markers. Each entry is a regex matched case-insensitively against the title.
_NON_NEWS_TITLE_RE = re.compile(
    r"\b("
    r"quiz|poll|gallery|opinion|"
    r"ranked|rated|rating:|"
    r"watch:|video:|photos?:|"
    r"guess\s+(?:the|who|which)|"
    r"can\s+you\s+(?:name|guess|spot|tell)|"
    r"on\s+this\s+day|years?\s+ago\s+today|"
    r"did\s+you\s+know|fun\s+facts?|"
    r"vote\s+for"
    r")\b",
    re.IGNORECASE,
)

# Listicle-fluff pattern: "10 TRICKY ...", "5 SHOCKING ...", "7 WEIRD ...".
# These are engagement bait, not news. Plain "5 takeaways" or "5 storylines"
# stays — those are analysis.
_LIST_FLUFF_RE = re.compile(
    r"^\d+\s+(tricky|fun|wild|weird|crazy|shocking|mind[-\s]?blowing|"
    r"insane|amazing|awkward|hilarious|brutal|savage|epic)\b",
    re.IGNORECASE,
)

# Promo / guide patterns — not factual news.
_GUIDE_RE = re.compile(
    r"^(?:"
    r"how\s+to\s+(?:stream|watch|follow|see|listen|tune|catch)|"
    r"where\s+to\s+(?:watch|stream|see|find)|"
    r"everything\s+you\s+need\s+to\s+know|"
    r"order\s+your|buy\s+(?:your|now|the)|shop\s+the|"
    r"pre[- ]?order|subscribe\s+to\s+(?:our|the)|"
    r"new\s+(?:issue|edition)\s+(?:on\s+sale|out)"
    r")\b",
    re.IGNORECASE,
)

# Anywhere-in-title commerce patterns. Caught the "ORDER YOUR FOURFOURTWO
# WORLD CUP 2026 WALL CHART" promo that was making it into Soccer Daily.
_COMMERCE_RE = re.compile(
    r"\b("
    r"wall\s+chart|"
    r"advent\s+calendar|"
    r"shop\s+now|"
    r"on\s+sale\s+now|"
    r"new\s+book\s+out|"
    r"merch(?:andise)?\s+drop"
    r")\b",
    re.IGNORECASE,
)

# Preview / teaser articles: the headline promises content (predictions,
# picks, odds, lineups) that lives in the article body, not on the slide.
# Without per-publisher body extraction, these read as empty teasers.
# Hits hardest in NBA/UFC/Soccer where betting-preview content is a
# big category. Conservative — only patterns where the title is *clearly*
# a container, not a real news event.
_TEASER_RE = re.compile(
    r"\b("
    # Combined predictions/picks/odds in any order, with comma OR &/and
    r"picks?\s*(?:&|and|,)\s*odds|"
    r"odds\s*(?:&|and|,)\s*picks?|"
    r"predictions?\s*[,&]\s+picks?|"
    r"predictions?\s*[,&]\s+odds|"
    r"odds\s*[,&]\s+predictions?|"
    r"picks?\s*[,&]\s+predictions?|"
    r"betting\s+(?:preview|tips|odds|lines?)|"
    r"fantasy\s+(?:picks?|preview|advice|projections?)|"
    r"\bdfs\s+(?:picks?|preview|lineup)|"
    r"best\s+bets?\b|"
    r"preview\s*[,&]\s+predictions?|"
    r"(?:game|match|fight)\s+\d+\s+predictions?|"
    r"\bvs\.?\s+\w+(?:\s+\w+)?\s+predictions?|"
    r"prop\s+bets?|player\s+props?|"
    r"how\s+to\s+bet|"
    r"starting\s+lineups?|projected\s+lineups?|"
    r"injury\s+report,?\s+(?:lineup|odds|starting)|"
    r"win\s+probabilit(?:y|ies)|"
    r"prediction\s+market|"
    r"power\s+rankings?|"
    r"by\s+the\s+numbers?|"
    r"stat\s+pack|"
    r"matchup\s+preview|"
    r"\bATS\s+(?:pick|trends?)|"
    r"betting\s+model|"
    # Parlay/spread/over-under = betting tease
    r"\d+[-\s]way\s+parlay|parlay\s+(?:pick|return|hit|of)|"
    r"\bsame[-\s]game\s+parlay|"
    r"against\s+the\s+spread|"
    r"\bover/under\b|over\s+or\s+under"
    r")\b",
    re.IGNORECASE,
)

# URL path keywords that indicate non-article content.
_NON_NEWS_URL_PARTS = (
    "/quiz/", "/quizzes/",
    "/gallery/", "/galleries/", "/photos/", "/photo/",
    "/video/", "/videos/", "/watch/",
    "/poll/", "/polls/",
    "/opinion/",
    "/podcast/", "/podcasts/",
)


# Severity keywords — used by `severity_of` to flag tragic / harm-related news.
# Light touch: this is just a heuristic to keep "BLOWING UP" copy off
# obituaries.
_SEVERE_RE = re.compile(
    r"\b("
    r"dies|dead|death|killed|fatal|fatality|"
    r"tragedy|tragic|mourn|grief|"
    r"hospital|hospitalised|hospitalized|coma|"
    r"crash|wreck|collision|accident|"
    r"injur(?:y|ed|ies)|surgery|broken|fractur(?:ed|e)|"
    r"arrest|charged|indicted|sentenced|"
    r"cancer|terminal|disease|illness|stroke|heart\s+attack"
    r")\b",
    re.IGNORECASE,
)


def is_news_content(article: Article) -> tuple[bool, str]:
    """Return (ok, reason). False means article should be dropped as non-news."""
    title = article.title.strip()
    if _NON_NEWS_TITLE_RE.search(title):
        m = _NON_NEWS_TITLE_RE.search(title)
        return False, f"non-news title pattern: {m.group(0)!r}"
    if _LIST_FLUFF_RE.search(title):
        return False, "listicle-fluff title"
    if _GUIDE_RE.search(title):
        return False, "guide/promo title"
    if _COMMERCE_RE.search(title):
        return False, "commerce/merch title"
    if _TEASER_RE.search(title):
        m = _TEASER_RE.search(title)
        return False, f"preview/teaser title: {m.group(0)!r}"
    if article.url:
        path = urlparse(article.url).path.lower()
        for part in _NON_NEWS_URL_PARTS:
            if part in path:
                return False, f"non-news URL path: {part}"
    return True, "ok"


def passes_filters(article: Article, *,
                   min_title_len: int = 20,
                   max_title_words: int = 18,
                   require_image: bool = True,
                   freshness_hours: int = 72,
                   # 400px is the smallest source we can sensibly upscale
                   # to a 1080-wide slide without it looking like soup.
                   # Anything smaller than that gets the article dropped.
                   min_image_width: int = 400,
                   blocklist: list[str] | None = None) -> tuple[bool, str]:
    title = article.title.strip()
    if len(title) < min_title_len:
        return False, f"title too short ({len(title)})"
    if len(title.split()) > max_title_words:
        return False, f"title too wordy ({len(title.split())} words)"
    if require_image and not article.image_url:
        return False, "no image"
    # Drop articles whose image is provably too small to render cleanly on
    # a 1080-wide slide. We only reject when the URL *encodes* a width hint
    # (`url_width_hint` returns 0 for "unknown" → we trust those by default).
    if min_image_width > 0 and article.image_url:
        # Local import to avoid a circular dep with `core.parsers`.
        from core.parsers.html_scraper import url_width_hint
        w = url_width_hint(article.image_url)
        if 0 < w < min_image_width:
            return False, f"image too small ({w}px)"
    if article.published_ts:
        age_h = (time.time() - article.published_ts) / 3600
        if age_h > freshness_hours:
            return False, f"stale ({age_h:.0f}h old)"
    bl = [w.lower() for w in (blocklist or [])]
    tl = title.lower()
    for w in bl:
        if w in tl:
            return False, f"blocklisted word: {w}"
    ok, reason = is_news_content(article)
    if not ok:
        return False, reason
    return True, "ok"


def severity_of(article: Article) -> str:
    """Return 'severe' if the article is tragic / harm-related, else 'normal'."""
    blob = f"{article.title} {article.description}"
    return "severe" if _SEVERE_RE.search(blob) else "normal"


# Mapping article phrasing → @f1newsflash-style sentiment icon.
_QUOTE_RE     = re.compile(r'(?:["“”]|\bsays\b|\bclaims\b|\btold\b|\badmits\b)', re.IGNORECASE)
_RUMOUR_RE    = re.compile(r'\b(could|might|expected|set\s+to|rumou?r|reportedly|believed\s+to|may)\b', re.IGNORECASE)
_NEGATION_RE  = re.compile(r"\b(doesn't|don't|won't|can't|isn't|aren't|denies|denied|rejects|reject|rules\s+out|not\s+\w+)\b", re.IGNORECASE)


def news_icon(article: Article) -> str:
    """Pick a one-character "type" indicator for the slide's corner badge.

    All glyphs are ASCII-safe so they render in any condensed sans-serif
    headline font (Anton / Bebas / Oswald don't carry the symbol blocks).

    Decision priority mirrors what @f1newsflash does:
      !  → severe / harm / crash / death / injury (urgent alert)
      "  → direct quote ("X says…", quoted phrasing)
      ?  → rumour, report, "could", "set to"
      X  → denial / negation / rules-out
      !  → default — plain breaking news
    """
    if severity_of(article) == "severe":
        return "!"
    blob = f"{article.title} {article.description}"
    if _QUOTE_RE.search(blob):
        return '"'
    if _NEGATION_RE.search(blob):
        return "X"
    if _RUMOUR_RE.search(blob):
        return "?"
    return "!"


# ── sentiment-driven emoji badge ────────────────────────────────────────────
#
# Replaces the ASCII `news_icon()` glyph with a colour emoji that matches
# the *mood* of the article. Designs render this with a colour-emoji font
# (Apple Color Emoji on macOS, Noto Color Emoji on Linux) at native 160px
# and downscale into the badge slot.
#
# Order is priority: the louder / sadder cues win over generic positives,
# so a "champion dies after crash" reads as 😢, not 🏆.

_DEATH_RE     = re.compile(r"\b(dies|died|death|deaths|fatal|fatally|passed\s+away|tragedy|tragic|funeral|killed|mourns?)\b", re.I)
_CRASH_RE     = re.compile(r"\b(crash|crashes|crashed|crashing|injury|injured|injures|hospital|hospitalised|hospitalized|surgery|critical|accident|smash(ed|es)?|collision)\b", re.I)
_FEUD_RE      = re.compile(r"\b(feud|clash|clashes|blasts?|slams?|blames?|attacks?|attacked|criticis(?:e|es|ed|ing|m|es)|fur(?:y|ious)|rant|hits?\s+out|war\s+of\s+words|fires?\s+back)\b", re.I)
_DENIAL_RE    = re.compile(r"\b(denies|denied|deny|rejects?|rejected|rules?\s+out|ruled\s+out|denial|dismiss(?:es|ed)?|shuts?\s+down|won'?t)\b", re.I)
_RUMOUR_EM_RE = re.compile(r"\b(could|might|expected|set\s+to|rumou?red?|rumou?rs?|reportedly|believed\s+to|may|possibly|linked\s+to|could\s+be|is\s+being\s+considered)\b", re.I)
_QUOTE_EM_RE  = re.compile(r'(?:["“”]|\b(?:says|claims|told|admits|reveals?|insists|warns)\b)', re.I)
_WIN_RE       = re.compile(r"\b(wins?|won|winner|champion|champions(?:hip)?|title|record|triumph|victory|takes\s+pole|pole\s+position|fastest\s+lap|gold|trophy|crowned)\b", re.I)
_HYPE_RE      = re.compile(r"\b(dominant|stunning|brilliant|fastest|incredible|amazing|epic|sensational|smashes?|on\s+fire|red[-\s]?hot|blistering)\b", re.I)
_RETURN_RE    = re.compile(r"\b(returns?|comeback|signs?|signed|joins?|announces?|announcement|new\s+deal|extends?|extension|launches?|unveils?|debut)\b", re.I)
_SHOCK_RE     = re.compile(r"\b(shock|shocking|shocked|unbelievable|drama|dramatic|bombshell|stunning\s+twist|jaw[-\s]?dropping)\b", re.I)


def news_emoji(article: Article) -> str:
    """Pick a colour emoji that matches the article's emotional register.

    Priority is loudest-first: death overrides crash, crash overrides
    feud, etc. A win headline that contains "shock" still resolves to
    🏆 because shock is checked late.
    """
    blob = f"{article.title} {article.description or ''}"
    if _DEATH_RE.search(blob):
        return "😢"
    if _CRASH_RE.search(blob) or severity_of(article) == "severe":
        return "🚨"
    if _FEUD_RE.search(blob):
        return "😡"
    if _DENIAL_RE.search(blob):
        return "🚫"
    if _WIN_RE.search(blob):
        return "🏆"
    if _HYPE_RE.search(blob):
        return "🔥"
    if _RETURN_RE.search(blob):
        return "💪"
    if _QUOTE_EM_RE.search(blob):
        return "💬"
    if _RUMOUR_EM_RE.search(blob):
        return "🤔"
    if _SHOCK_RE.search(blob):
        return "😱"
    return "📰"


_EMOJI_FONT_CANDIDATES = (
    "/System/Library/Fonts/Apple Color Emoji.ttc",                      # macOS
    "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",                 # Debian/Ubuntu
    "/usr/share/fonts/google-noto-emoji/NotoColorEmoji.ttf",             # Fedora
    "/usr/share/fonts/noto/NotoColorEmoji.ttf",                          # Arch
)


def emoji_font_path() -> str | None:
    """First existing colour-emoji font on this machine, or None.

    Caller decides what to do if no font is found — usually fall back to
    the legacy ASCII-glyph badge so the slide still renders.
    """
    import os
    for p in _EMOJI_FONT_CANDIDATES:
        if os.path.exists(p):
            return p
    return None


def score_article(a: Article, *, boost: list[str] | None = None) -> float:
    """Soft ranking: bigger = more carousel-worthy.

    Heuristic, calibrated for short feeds:
      +2.0  has image
      +1.5  has description >= 60 chars
      +1.0  title 35–90 chars (sweet spot — readable but punchy)
      +0.5  title contains a digit (often signals scoreline / age / standings)
      +1.0  recent (<24h)
      −1.5  tragic / harm-related (still let it through, but rank below upbeat news)
    """
    s = 0.0
    if a.image_url:
        s += 2.0
        # Penalise (but don't reject) URLs that still look low-res after
        # the enricher's upgrade pass. Pushes them below otherwise-equal
        # candidates with a clean press shot.
        from core.parsers.html_scraper import looks_low_res
        if looks_low_res(a.image_url):
            s -= 1.2
    if a.description and len(a.description) >= 60:
        s += 1.5
    n = len(a.title)
    if 35 <= n <= 90:
        s += 1.0
    elif n < 25 or n > 130:
        s -= 0.5
    if any(ch.isdigit() for ch in a.title):
        s += 0.5
    if a.published_ts:
        age_h = (time.time() - a.published_ts) / 3600
        if age_h < 24:
            s += 1.0
        elif age_h > 60:
            s -= 0.5
    if severity_of(a) == "severe":
        s -= 1.5
    # Boost score if the topic owner specifically asked for these words.
    # Catches the "Arsenal-Atletico story missed the carousel" complaint:
    # `boost: [arsenal, atletico, mudryk]` ensures those subjects float
    # to the top regardless of the day's general news mix.
    if boost:
        blob = f"{a.title} {a.description}".lower()
        for kw in boost:
            if kw and kw.lower() in blob:
                s += 1.5
    return s


def balance_sources(articles: list[Article], count: int,
                    *, max_per_source: int | None = None,
                    key=None) -> list[Article]:
    """Round-robin pick across sources so a carousel doesn't end up all
    from one outlet — the F1 carousel was a perfect demo, every slide
    came from formula1.com and they all shared the same studio image.

    Articles are expected to be pre-sorted by score (best first). The
    round-robin then guarantees source diversity inside the top-N.

    `max_per_source` caps how many slots any single group can claim.
    Defaults to `count // 2 + 1` — for a 5-slide carousel that means a
    single source can take at most 3 slots, leaving room for at least
    two other publishers.

    `key` lets the caller pick the grouping dimension (defaults to
    article source). Sports Digest uses `extra["origin_topic"]` so the
    round-robin diversifies across sports instead of publishers.
    """
    if max_per_source is None:
        max_per_source = max(1, count // 2 + 1)
    if key is None:
        key = lambda a: a.source

    by_source: dict[str, list[Article]] = defaultdict(list)
    for a in articles:
        by_source[key(a)].append(a)
    # Trim each source's pool to the cap up-front so the round-robin
    # never even sees the surplus.
    for s in list(by_source):
        by_source[s] = by_source[s][:max_per_source]
    sources = list(by_source.keys())
    out: list[Article] = []
    i = 0
    safety = 0
    while len(out) < count and any(by_source.values()):
        s = sources[i % len(sources)]
        if by_source.get(s):
            out.append(by_source[s].pop(0))
        i += 1
        safety += 1
        if safety > count * len(sources) + 20:
            break
    return out

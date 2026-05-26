"""Seamless design — 3 stories paired across a 7-slide carousel.

Visual pattern borrowed from the @anastasiya_gozhenkina / @gloriwht
"бесшовные карусели" style. Each story occupies a **2-slide pair**
where the article's hero photo bleeds across both tiles, and the text
splits headline → key fact:

    pair 1                pair 2                pair 3              cta
  ┌──────┬──────┐ ┌──────┬──────┐ ┌──────┬──────┐ ┌──────┐
  │ 1/7  │ 2/7  │ │ 3/7  │ 4/7  │ │ 5/7  │ 6/7  │ │ 7/7  │
  │ ◄photo A ► │ │ ◄photo B ► │ │ ◄photo C ► │ │ brand │
  │ HEAD │ fact │ │ HEAD │ fact │ │ HEAD │ fact │ │FOLLOW│
  └──────┴──────┘ └──────┴──────┘ └──────┴──────┘ └──────┘

Why 2-slide pairs (vs 6-slide single-panorama like the original draft):
  * 2160×1350 target only needs ~1.25× upscale from a 1920×1080 hero
    → no blurred outpaint gutters, all slides stay sharp.
  * Shows 3 stories per carousel instead of 1, matching the news pool
    we actually have.
  * "Tease → reveal" rhythm (headline → fact) hits the swipe-through
    bait pattern naturally.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from core.http import download_images_parallel
from core.image import smart_cover
from core.log import get_logger
from core.parsers.base import Article
from core.quality import emoji_font_path
from core.text import clean_description, clean_headline, punchy
from core.topic_loader import TopicConfig
from core.typography import balanced_wrap, fit_font

from designs.base import Design

log = get_logger("design.seamless")

CORE_FONTS = Path(__file__).resolve().parent.parent / "core" / "assets" / "fonts"
FALLBACK_HEADLINE = str(CORE_FONTS / "Anton-Regular.ttf")
FALLBACK_BODY = str(CORE_FONTS / "BebasNeue-Regular.ttf")

WHITE = (255, 255, 255)
SOFT_WHITE = (235, 235, 235)
BLACK = (0, 0, 0)

# Carousel structure constants. Could be parametrised from topic.yaml
# later, but these defaults match the reference Threads posts (~7 slides).
PAIRS = 3              # number of stories per carousel
SLIDES_PER_PAIR = 2    # each story spans this many slides
# Total slides = PAIRS * SLIDES_PER_PAIR + 1  (last one is the CTA)


def _font(path: str | None, size: int, fallback: str) -> ImageFont.FreeTypeFont:
    p = path if (path and os.path.exists(path)) else fallback
    try:
        return ImageFont.truetype(p, size)
    except OSError:
        return ImageFont.load_default()


# ── panorama builder (for a single pair) ──────────────────────────────────


def _build_panorama(photo_path: str | None, target_w: int, target_h: int) -> Image.Image:
    """Build a `target_w × target_h` canvas from one article photo.

    Sized for a single pair (2160×1350 by default) — at this scale a
    standard 1920×1080 hero needs only ~1.25× upscale via smart_cover,
    so we never need blurred outpaint extensions. Falls back to flat
    dark if the photo is missing or fails to load.
    """
    if not photo_path or not os.path.exists(photo_path):
        return Image.new("RGB", (target_w, target_h), (18, 18, 18))
    try:
        img = Image.open(photo_path).convert("RGB")
    except Exception as e:
        log.warning("panorama load failed: %s", e)
        return Image.new("RGB", (target_w, target_h), (18, 18, 18))

    src_ar = img.width / img.height
    tgt_ar = target_w / target_h

    # If source is much narrower than 2-slide aspect, blend rather than
    # blur-extend (rare for news hero photos which are usually 1.6:1+).
    if src_ar < tgt_ar * 0.6:
        # Height-fit, paste centred, mirror+blur gutters.
        new_h = target_h
        new_w = max(1, int(img.width * (target_h / img.height)))
        img = img.resize((new_w, new_h), Image.LANCZOS)
        canvas = Image.new("RGB", (target_w, target_h), BLACK)
        x_off = (target_w - new_w) // 2
        canvas.paste(img, (x_off, 0))
        if x_off > 0:
            sample_w = min(x_off, new_w)
            for x_target, slice_box in (
                (0, (0, 0, sample_w, new_h)),
                (x_off + new_w, (new_w - sample_w, 0, new_w, new_h)),
            ):
                strip = img.crop(slice_box).transpose(Image.FLIP_LEFT_RIGHT)
                gutter_w = (
                    x_off if x_target == 0
                    else target_w - (x_off + new_w)
                )
                if strip.width != gutter_w and gutter_w > 0:
                    strip = strip.resize((gutter_w, new_h), Image.LANCZOS)
                strip = strip.filter(ImageFilter.GaussianBlur(radius=38))
                canvas.paste(strip, (x_target, 0))
        return canvas

    return smart_cover(img, target_w, target_h, prefer_top=True)


# ── CTA backdrop (last slide) ─────────────────────────────────────────────


def _build_photo_stack_backdrop(topic: TopicConfig, photos: list[str | None],
                                W: int, H: int) -> Image.Image:
    """Reusable backdrop = a tilted stack of the carousel's hero photos
    rendered as little polaroid-style cards on a dark page. Used by
    both the cover slide and the final save-bait slide — same visual
    grammar at the start and end so the carousel reads as one unit.
    """
    bg = topic.brand.bg or (12, 12, 16)
    canvas = Image.new("RGB", (W, H), bg)

    # Subtle vertical gradient — slightly lighter at top, fades down.
    # Gives the backdrop depth without competing with the photos.
    accent = topic.brand.accent or (220, 60, 80)
    grad = Image.new("RGB", (1, H), bg)
    for y in range(H):
        t = 1.0 - (y / max(1, H - 1))
        blend = (t ** 2.5) * 0.18
        r = int(bg[0] * (1 - blend) + accent[0] * blend)
        g = int(bg[1] * (1 - blend) + accent[1] * blend)
        b = int(bg[2] * (1 - blend) + accent[2] * blend)
        grad.putpixel((0, y), (r, g, b))
    canvas = grad.resize((W, H))

    # Build mini polaroid cards from up to 3 article photos.
    card_w, card_h = 320, 380
    photo_w, photo_h = 284, 284
    photo_x = (card_w - photo_w) // 2
    photo_y = 18
    cards: list[Image.Image] = []
    for photo_path in (photos or []):
        if not photo_path or not os.path.exists(photo_path):
            continue
        card = Image.new("RGBA", (card_w, card_h), (0, 0, 0, 0))
        cd = ImageDraw.Draw(card)
        cd.rounded_rectangle([0, 0, card_w, card_h], radius=4,
                             fill=(246, 244, 238, 255))
        try:
            img = Image.open(photo_path).convert("RGB")
            img = smart_cover(img, photo_w, photo_h, prefer_top=True)
            card.paste(img, (photo_x, photo_y))
        except Exception as e:
            log.warning("cta card photo failed (%s): %s", photo_path, e)
            cd.rectangle(
                [photo_x, photo_y, photo_x + photo_w, photo_y + photo_h],
                fill=(190, 188, 180, 255),
            )
        cards.append(card)
        if len(cards) >= 3:
            break

    if not cards:
        return canvas  # fallback: clean gradient, no photo stack

    # Tilt + offset each card. Stack falls roughly along a curved line
    # from upper-left to lower-right so the bottom-left card lies in
    # the safe zone for the brand chip / CTA text.
    placements = [
        (W // 2 - 320, 60,  -7),   # back card, leans left
        (W // 2 - 100, 110,  5),   # middle card, leans right
        (W // 2 + 60,  80,  -3),   # front card, leans left a bit
    ][:len(cards)]

    canvas_rgba = canvas.convert("RGBA")
    for card, (x, y, angle) in zip(cards, placements):
        # Drop shadow first so it sits under the rotated card.
        rotated = card.rotate(angle, resample=Image.BICUBIC, expand=True)
        shadowed = _card_shadow(rotated)
        sx, sy = x - 24, y - 24  # account for shadow padding
        canvas_rgba.alpha_composite(shadowed, (sx, sy))
    canvas = canvas_rgba.convert("RGB")

    # Dim the lower half so the CTA text reads cleanly on top of any
    # stray photo bits that intrude into the text zone.
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    fade_start = int(H * 0.48)
    for y in range(fade_start, H):
        t = (y - fade_start) / max(1, H - fade_start - 1)
        a = int((t ** 1.6) * 220)
        od.line([(0, y), (W, y)], fill=(*bg, a))
    canvas_rgba = canvas.convert("RGBA")
    canvas_rgba.alpha_composite(overlay)
    return canvas_rgba.convert("RGB")


def _card_shadow(card: Image.Image) -> Image.Image:
    """Soft drop shadow under a (rotated) polaroid card. Returns an
    RGBA image larger than `card` so the shadow fits."""
    pad = 24
    sw, sh = card.width + pad * 2, card.height + pad * 2
    shadow = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
    alpha = card.split()[-1]
    mask = Image.new("L", (sw, sh), 0)
    mask.paste(alpha, (pad, pad + 8))
    mask = mask.filter(ImageFilter.GaussianBlur(radius=12))
    fill = Image.new("RGBA", (sw, sh), (0, 0, 0, 140))
    shadow.paste(fill, (0, 0), mask)
    shadow.alpha_composite(card, (pad, pad))
    return shadow


# ── content planning ──────────────────────────────────────────────────────


def _split_into_sentences(text: str) -> list[str]:
    if not text:
        return []
    text = re.sub(r"\s+", " ", text).strip()
    parts = re.split(r"(?<=[.!?])\s+(?=[A-ZА-Я])", text)
    return [p.strip(" .,;:—-") for p in parts if p.strip()]


def _first_good_sentence(article: Article) -> str:
    """Best 'fact' line for the reveal slide: first description sentence
    that's long enough to be informative but short enough to render at
    a readable size."""
    body = clean_description(article.description or "", max_chars=400)
    for s in _split_into_sentences(body):
        if 25 <= len(s) <= 200:
            return s
    # Fall back to whole body if no sentence fits the window
    return body or ""


def _split_headline_for_bait(headline: str) -> tuple[str, str]:
    """Split a headline into (bait, reveal) for the two-slide pair.

    Bait is the first portion ending in an ellipsis, designed to leave
    the viewer wanting the rest. Reveal is the punch — the part that
    pays off the swipe.

    Strategy:
      1. Look for a preposition / conjunction near the middle of the
         sentence — natural breath points in English news headlines.
      2. Fall back to splitting at the word boundary closest to 50%.
      3. If the headline is short (≤5 words), don't split — both
         slides get the same headline; the design degrades gracefully.
    """
    words = headline.split()
    if len(words) <= 5:
        return headline, ""

    n = len(words)
    # Words that signal a natural break in English news headlines. Order
    # matters: 'AT' / 'AFTER' / 'AS' usually lead into the substantive
    # part of the story, so we prefer those.
    BREAK_WORDS = (
        "AT", "AFTER", "BEFORE", "AS", "WITH", "FOR", "BY", "FROM",
        "ON", "DURING", "DESPITE", "AGAINST", "OVER", "ABOUT",
        "AND", "BUT", "WHILE", "BECAUSE",
    )
    upper = [w.strip(",.:;!?\"").upper() for w in words]
    # Best break point: one of BREAK_WORDS landing in the middle 40-65%
    # of the headline. We index into words[] using the position so the
    # original casing/punctuation is preserved on either side.
    best_i = -1
    best_dist = 9999
    for i, w in enumerate(upper):
        if w in BREAK_WORDS and 0.30 * n <= i <= 0.70 * n:
            target = int(n * 0.5)
            if abs(i - target) < best_dist:
                best_dist = abs(i - target)
                best_i = i
    if best_i == -1:
        # No preposition landed in the comfortable middle band — pick
        # the midpoint, then walk forward past leading function words
        # so the reveal slide doesn't open with an orphaned "THE" / "OF"
        # / "TO" that reads as broken English.
        LEAD_STOPS = {"THE", "A", "AN", "OF", "TO", "IN", "ON"}
        best_i = max(2, n // 2)
        while best_i < n - 1 and upper[best_i] in LEAD_STOPS:
            best_i += 1

    bait_words = words[:best_i]
    reveal_words = words[best_i:]
    bait = " ".join(bait_words).rstrip(",.;: ") + "…"
    reveal = " ".join(reveal_words)
    return bait, reveal


def _plan_pair(article: Article, pair_idx: int, total_pairs: int) -> list[dict]:
    """Two slots for one article's pair, designed as bait → reveal.

    Slide A (bait): a fragment of the headline ending in '…' that
                    invites the viewer to swipe for the rest. Photo
                    is the visual hook.
    Slide B (reveal): the rest of the headline as the big payoff,
                      with the supporting fact sentence in smaller
                      body type underneath. Same photo, darkened to
                      a moody backdrop so the text dominates.
    """
    headline_eyebrow = f"STORY · {pair_idx:02d} OF {total_pairs:02d}"
    reveal_eyebrow = f"VIA {article.source.upper()}"
    headline = punchy(clean_headline(article.title)).upper()
    bait, reveal = _split_headline_for_bait(headline)
    fact = _first_good_sentence(article)
    return [
        {"kind": "bait",   "text": bait,   "eyebrow": headline_eyebrow},
        {"kind": "reveal", "text": reveal or headline,
         "fact": fact, "eyebrow": reveal_eyebrow},
    ]


# ── per-slide text rendering ──────────────────────────────────────────────


def _draw_blank_counter(img: Image.Image, slide_num: int, total: int,
                        topic: TopicConfig) -> None:
    """(Reserved for future use — currently every slide gets either a
    headline/fact text block or a CTA. Kept for parametrisation later if
    we want middle slides without any text overlay.)"""
    W, H = img.size
    d = ImageDraw.Draw(img, "RGBA")
    body_path = topic.brand.font_body or FALLBACK_BODY
    counter_font = _font(body_path, 22, FALLBACK_BODY)
    counter = f"{slide_num:02d} / {total:02d}"
    cb = counter_font.getbbox(counter)
    cw = cb[2] - cb[0]
    pad, margin = 12, 40
    pill_h = (cb[3] - cb[1]) + 12
    x1, y1 = W - margin, H - margin
    x0 = x1 - cw - pad * 2
    y0 = y1 - pill_h
    d.rounded_rectangle([x0, y0, x1, y1], radius=pill_h // 2,
                        fill=(0, 0, 0, 160))
    d.text((x0 + pad, y0 + (pill_h - (cb[3] - cb[1])) // 2 - cb[1]),
           counter, font=counter_font, fill=SOFT_WHITE)


def _emoji_glyph(char: str, target_h: int) -> Image.Image | None:
    """Render a single emoji codepoint as an RGBA image of height ~target_h.

    Apple Color Emoji and Noto Color Emoji are bitmap fonts (SBIX /
    CBDT) with discrete strike sizes — PIL can only load them at one
    of those exact sizes. We probe a small ladder of common strikes
    until one loads, render the glyph there, then resize down to the
    target body-text height.

    Returns None when no colour-emoji font is on the system. The caller
    falls back to a plain ASCII bullet so the slide still renders
    cleanly on stripped-down Linux installs without Noto Color Emoji.
    """
    path = emoji_font_path()
    if not path or not char:
        return None
    # Apple Color Emoji exposes strikes at 20/32/40/48/64/96/160.
    # Pick a strike ≥ target_h and as close as possible to it; a small
    # downscale on a bitmap-emoji render is fine, an upscale isn't.
    for strike in (32, 40, 48, 64, 96, 160, 20):
        if strike >= target_h or strike == 20:
            try:
                font = ImageFont.truetype(path, strike)
                break
            except OSError:
                continue
    else:
        return None
    try:
        bbox = font.getbbox(char)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        if w <= 0 or h <= 0:
            return None
        img = Image.new("RGBA", (w + 4, h + 4), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.text((-bbox[0] + 2, -bbox[1] + 2), char, font=font,
               embedded_color=True)
        if h != target_h:
            scale = target_h / h
            img = img.resize(
                (max(1, int((w + 4) * scale)), max(1, int((h + 4) * scale))),
                Image.LANCZOS,
            )
        return img
    except Exception as e:
        log.debug("emoji render failed for %r: %s", char, e)
        return None


def _darken_full(img: Image.Image, opacity: float = 0.62) -> None:
    """Heavy darken pass for the reveal slide — turns the hero photo into
    a moody backdrop so the text dominates without losing the visual
    continuity with slide A."""
    W, H = img.size
    base = img.convert("RGBA")
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, int(255 * opacity)))
    base.alpha_composite(overlay)
    img.paste(base.convert("RGB"))


def _draw_bait_slide(img: Image.Image, slot: dict, topic: TopicConfig,
                     slide_num: int, total: int) -> None:
    """Slide A — full-bleed photo, ellipsis-terminated headline fragment
    at the bottom over a gradient scrim. Designed to leave the viewer
    wanting the rest."""
    W, H = img.size
    accent_light = topic.brand.accent_light or (255, 130, 130)
    headline_path = topic.brand.font_headline or FALLBACK_HEADLINE
    body_path = topic.brand.font_body or FALLBACK_BODY

    # Bottom scrim — same as before, fades from transparent at 42% down.
    scrim_top = int(H * 0.42)
    scrim_h = H - scrim_top
    overlay = Image.new("RGBA", (W, scrim_h), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    for y in range(scrim_h):
        t = y / max(1, scrim_h - 1)
        a = int((t ** 1.8) * 230)
        od.line([(0, y), (W, y)], fill=(0, 0, 0, a))
    base = img.convert("RGBA")
    base.alpha_composite(overlay, (0, scrim_top))
    img.paste(base.convert("RGB"))

    d = ImageDraw.Draw(img)
    margin = 80
    safe_w = W - margin * 2
    footer_y = H - margin - 28
    text_bottom = footer_y - 50

    # Big bait headline — last "..." token gets the accent treatment.
    font, lines = fit_font(
        headline_path, slot["text"], max_w=safe_w,
        max_size=110, min_size=60, max_lines=3,
    )
    line_h = font.getbbox("Hg")[3] + 10
    block_h = line_h * len(lines)
    text_y = text_bottom - block_h
    for ln in lines:
        d.text((margin, text_y), ln, font=font, fill=WHITE)
        text_y += line_h

    _draw_eyebrow_footer(img, d, slot, topic, slide_num, total,
                         body_path, accent_light,
                         block_top=text_bottom - block_h,
                         footer_y=footer_y, margin=margin)


def _draw_reveal_slide(img: Image.Image, slot: dict, topic: TopicConfig,
                       slide_num: int, total: int) -> None:
    """Slide B — same photo darkened heavily, big payoff text fills the
    upper-middle, supporting fact sentence sits below in body type.
    The visual rhythm is 'tease (A) → loud reveal (B)' on swipe."""
    W, H = img.size
    accent = topic.brand.accent or (220, 60, 80)
    accent_light = topic.brand.accent_light or (255, 130, 130)
    headline_path = topic.brand.font_headline or FALLBACK_HEADLINE
    body_path = topic.brand.font_body or FALLBACK_BODY

    # Heavy darken — photo becomes a backdrop. We keep some of the
    # photo visible (62% black) so the colour palette ties slide B
    # to slide A; a flat black would feel disconnected.
    _darken_full(img, opacity=0.62)

    d = ImageDraw.Draw(img)
    margin = 80
    safe_w = W - margin * 2
    footer_y = H - margin - 28

    # Layout: reveal text occupies the middle band. Fact sits below.
    reveal_font, reveal_lines = fit_font(
        headline_path, slot["text"], max_w=safe_w,
        max_size=126, min_size=66, max_lines=3,
    )
    reveal_line_h = reveal_font.getbbox("Hg")[3] + 10
    reveal_block_h = reveal_line_h * len(reveal_lines)

    fact_text = slot.get("fact") or ""
    fact_block_h = 0
    fact_font = None
    fact_lines: list[str] = []
    if fact_text:
        fact_font, fact_lines = fit_font(
            body_path, fact_text, max_w=safe_w,
            max_size=42, min_size=26, max_lines=4,
        )
        fact_line_h = int(fact_font.size * 1.32)
        fact_block_h = fact_line_h * len(fact_lines)

    # Vertically centre the (reveal + gap + fact) bundle in the area
    # between the eyebrow zone and the footer.
    gap = 36 if fact_text else 0
    bundle_h = reveal_block_h + gap + fact_block_h
    eyebrow_zone_top = int(H * 0.18)
    available_h = (footer_y - 80) - eyebrow_zone_top
    top = eyebrow_zone_top + max(0, (available_h - bundle_h) // 2)

    # Draw reveal headline. Last word in accent_light to land the punch.
    text_y = top
    for i, ln in enumerate(reveal_lines):
        if i == len(reveal_lines) - 1 and " " in ln:
            rest, last = ln.rsplit(" ", 1)
            rest_w = (reveal_font.getbbox(rest + " ")[2]
                      - reveal_font.getbbox(rest + " ")[0])
            d.text((margin, text_y), rest + " ", font=reveal_font, fill=WHITE)
            d.text((margin + rest_w, text_y), last,
                   font=reveal_font, fill=accent_light)
        else:
            d.text((margin, text_y), ln, font=reveal_font, fill=WHITE)
        text_y += reveal_line_h

    # Draw fact text below the reveal headline.
    if fact_text and fact_font:
        fact_y = top + reveal_block_h + gap
        for ln in fact_lines:
            d.text((margin, fact_y), ln, font=fact_font, fill=SOFT_WHITE)
            fact_y += int(fact_font.size * 1.32)

    _draw_eyebrow_footer(img, d, slot, topic, slide_num, total,
                         body_path, accent_light,
                         block_top=top, footer_y=footer_y, margin=margin)


def _draw_cover_slide(img: Image.Image, slot: dict, topic: TopicConfig,
                      slide_num: int, total: int) -> None:
    """Slide 1 — the thumbstop. Photo stack lives in the upper half (the
    backdrop builder already placed it). On top of that we paint a
    bold hook headline + a date eyebrow, designed to answer 'is this
    for me?' and 'what do I get if I swipe?' in ≤0.7 seconds.

    Carries the bulk of the carousel's reach: in the 2026 IG/TikTok
    algorithm a high swipe-through rate from the cover gets the
    carousel distributed to 3–5× more non-followers."""
    W, H = img.size
    accent_light = topic.brand.accent_light or (255, 130, 130)
    headline_path = topic.brand.font_headline or FALLBACK_HEADLINE
    body_path = topic.brand.font_body or FALLBACK_BODY

    # Bottom fade so the hook sits on a solid dark band.
    bg = topic.brand.bg or (12, 12, 16)
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    fade_start = int(H * 0.48)
    for y in range(fade_start, H):
        t = (y - fade_start) / max(1, H - fade_start - 1)
        a = int((t ** 1.4) * 230)
        od.line([(0, y), (W, y)], fill=(*bg, a))
    base = img.convert("RGBA")
    base.alpha_composite(overlay)
    img.paste(base.convert("RGB"))

    d = ImageDraw.Draw(img)
    margin = 80
    safe_w = W - margin * 2
    footer_y = H - margin - 28

    # Hook headline — biggest type on the slide. Splits the "{N}" and
    # the rest visually: "{N} stories blowing up / in sports right now".
    hook_text = slot.get("text") or "TOP STORIES TODAY"
    pre_lines = [ln.strip() for ln in hook_text.split("\n") if ln.strip()]
    hook_font = _font(headline_path, 118, FALLBACK_HEADLINE)
    hook_lines: list[str] = []
    for ln in pre_lines:
        wrapped = balanced_wrap(ln, hook_font, safe_w, max_lines=2)
        hook_lines.extend(wrapped)
    if len(hook_lines) > 3:
        hook_font = _font(headline_path, 92, FALLBACK_HEADLINE)
        hook_lines = balanced_wrap(" ".join(pre_lines), hook_font,
                                   safe_w, max_lines=3)

    line_h = hook_font.getbbox("Hg")[3] + 10
    block_h = line_h * len(hook_lines)

    sub_text = slot.get("subtext") or ""
    sub_font = _font(body_path, 28, FALLBACK_BODY)
    sub_lines = balanced_wrap(sub_text, sub_font, safe_w, max_lines=2) if sub_text else []
    sub_line_h = int(sub_font.size * 1.32)
    sub_block_h = sub_line_h * len(sub_lines)

    bundle_gap = 18 if sub_lines else 0
    bundle_h = block_h + bundle_gap + sub_block_h
    text_bottom = footer_y - 60
    text_y = text_bottom - bundle_h

    # First line of the hook lands in the accent colour for instant
    # pattern interrupt — colour shift is what stops the thumb on a
    # scrolling feed.
    for i, ln in enumerate(hook_lines):
        # Highlight a digit at the start ("3 STORIES …") in accent so
        # the eye snaps to the number — proven thumbstop pattern.
        if i == 0 and ln.split() and ln.split()[0].rstrip(".,").isdigit():
            first, *rest = ln.split(" ", 1)
            rest = rest[0] if rest else ""
            first_w = (hook_font.getbbox(first + " ")[2]
                       - hook_font.getbbox(first + " ")[0])
            d.text((margin, text_y), first + " ",
                   font=hook_font, fill=accent_light)
            if rest:
                d.text((margin + first_w, text_y), rest,
                       font=hook_font, fill=WHITE)
        else:
            d.text((margin, text_y), ln, font=hook_font, fill=WHITE)
        text_y += line_h

    if sub_lines:
        sub_y = text_bottom - sub_block_h
        for ln in sub_lines:
            d.text((margin, sub_y), ln, font=sub_font, fill=SOFT_WHITE)
            sub_y += sub_line_h

    _draw_eyebrow_footer(img, d, slot, topic, slide_num, total,
                         body_path, accent_light,
                         block_top=text_bottom - bundle_h,
                         footer_y=footer_y, margin=margin)


def _draw_cta_slide(img: Image.Image, slot: dict, topic: TopicConfig,
                    slide_num: int, total: int) -> None:
    """Final slide — polaroid stack of the carousel's photos sits in the
    upper half (built by `_build_photo_stack_backdrop`), text CTA fills the
    bottom. The headline is the topic's own CTA copy (multi-line) so
    it reflects the topic identity, with the punch word picking up
    the accent colour. Sub-text adds context, the topic handle (or a
    fallback) acts as the destination."""
    W, H = img.size
    accent_light = topic.brand.accent_light or (255, 130, 130)
    headline_path = topic.brand.font_headline or FALLBACK_HEADLINE
    body_path = topic.brand.font_body or FALLBACK_BODY

    d = ImageDraw.Draw(img)
    margin = 80
    safe_w = W - margin * 2
    footer_y = H - margin - 28

    # Multi-line CTA headline. Honour any \n the topic.yaml ships, but
    # also wrap if a single line wouldn't fit.
    raw = slot.get("text") or "FOLLOW FOR MORE"
    pre_lines = [ln.strip() for ln in raw.split("\n") if ln.strip()]
    headline_lines: list[str] = []
    cta_font = _font(headline_path, 96, FALLBACK_HEADLINE)
    for ln in pre_lines:
        wrapped = balanced_wrap(ln, cta_font, safe_w, max_lines=2)
        headline_lines.extend(wrapped)
    if len(headline_lines) > 3:
        # Headline is huge — try a smaller font and re-wrap as one block
        cta_font = _font(headline_path, 78, FALLBACK_HEADLINE)
        headline_lines = balanced_wrap(" ".join(pre_lines), cta_font,
                                       safe_w, max_lines=3)

    line_h = cta_font.getbbox("Hg")[3] + 10
    block_h = line_h * len(headline_lines)

    # Subtitle: either a plain "subtext" string, or a list of
    # (emoji_char, text_str) `bullets` to render with the system
    # colour-emoji font. The save-bait outro uses the bullets path —
    # emoji glyphs land as colour artwork next to each action line.
    sub_text = slot.get("subtext") or ""
    bullets: list[tuple[str, str]] = slot.get("bullets") or []
    sub_font = _font(body_path, 30, FALLBACK_BODY)
    sub_line_h = int(sub_font.size * 1.42)
    if bullets:
        sub_block_h = sub_line_h * len(bullets)
        sub_lines = []
    else:
        sub_lines = balanced_wrap(sub_text, sub_font, safe_w, max_lines=2) if sub_text else []
        sub_block_h = sub_line_h * len(sub_lines)

    # Position the bundle: anchored to the bottom-third of the slide,
    # above the footer pills, so the photo stack above stays uncrowded.
    bundle_gap = 24 if (sub_lines or bullets) else 0
    bundle_h = block_h + bundle_gap + sub_block_h
    text_bottom = footer_y - 60
    text_y = text_bottom - bundle_h

    # Headline: last word picks up the accent so the CTA has a punch.
    for i, ln in enumerate(headline_lines):
        if i == len(headline_lines) - 1 and " " in ln:
            rest, last = ln.rsplit(" ", 1)
            rest_w = (cta_font.getbbox(rest + " ")[2]
                      - cta_font.getbbox(rest + " ")[0])
            d.text((margin, text_y), rest + " ", font=cta_font, fill=WHITE)
            d.text((margin + rest_w, text_y), last,
                   font=cta_font, fill=accent_light)
        else:
            d.text((margin, text_y), ln, font=cta_font, fill=WHITE)
        text_y += line_h

    sub_y = text_bottom - sub_block_h
    if bullets:
        glyph_h = int(sub_font.size * 0.92)
        for emoji_char, text in bullets:
            x = margin
            glyph = _emoji_glyph(emoji_char, glyph_h)
            if glyph:
                # Align glyph's vertical centre with the text's cap height.
                gy = sub_y + (sub_font.size - glyph.height) // 2 + 2
                img.paste(glyph, (x, gy), glyph)
                x += glyph.width + 14
            else:
                # Fallback: plain ASCII bullet so the slide still parses
                # on Linux installs without Noto Color Emoji.
                d.text((x, sub_y), "→", font=sub_font, fill=accent_light)
                x += sub_font.getbbox("→ ")[2]
            d.text((x, sub_y), text, font=sub_font, fill=SOFT_WHITE)
            sub_y += sub_line_h
    else:
        for ln in sub_lines:
            d.text((margin, sub_y), ln, font=sub_font, fill=SOFT_WHITE)
            sub_y += sub_line_h

    _draw_eyebrow_footer(img, d, slot, topic, slide_num, total,
                         body_path, accent_light,
                         block_top=text_bottom - bundle_h,
                         footer_y=footer_y, margin=margin)


def _draw_eyebrow_footer(img: Image.Image, d: ImageDraw.ImageDraw,
                         slot: dict, topic: TopicConfig,
                         slide_num: int, total: int,
                         body_path: str, accent_light: tuple,
                         *, block_top: int, footer_y: int,
                         margin: int) -> None:
    """Eyebrow (above text block) + topic/counter pills (bottom).
    Extracted from the old monolithic _draw_slide so all three slide
    kinds share the same chrome."""
    # Eyebrow above the text — pill-style so it reads on any photo.
    if slot.get("eyebrow"):
        eb_font = _font(body_path, 26, FALLBACK_BODY)
        eb_text = slot["eyebrow"]
        bb = eb_font.getbbox(eb_text)
        eb_w = bb[2] - bb[0]
        eb_h = (bb[3] - bb[1]) + 14
        eb_y = max(40, block_top - 22 - eb_h)
        pad = 12
        d.rounded_rectangle(
            [margin - pad, eb_y, margin + eb_w + pad, eb_y + eb_h],
            radius=eb_h // 2, fill=(0, 0, 0, 200),
        )
        d.text((margin, eb_y + (eb_h - (bb[3] - bb[1])) // 2 - bb[1]),
               eb_text, font=eb_font, fill=accent_light)

    # Topic + counter pills at the bottom.
    counter_font = _font(body_path, 24, FALLBACK_BODY)
    counter = f"{slide_num:02d} / {total:02d}"
    topic_label = (topic.display_name or topic.slug).upper()
    cb = counter_font.getbbox(counter)
    tb = counter_font.getbbox(topic_label)
    pill_h = max(cb[3], tb[3]) + 14
    pill_y = footer_y - pill_h // 2 - 4
    pad = 12

    tw = tb[2] - tb[0]
    d.rounded_rectangle(
        [margin - pad, pill_y, margin + tw + pad, pill_y + pill_h],
        radius=pill_h // 2, fill=(0, 0, 0, 180),
    )
    d.text((margin, pill_y + (pill_h - (tb[3] - tb[1])) // 2 - tb[1]),
           topic_label, font=counter_font, fill=SOFT_WHITE)

    cw = cb[2] - cb[0]
    cx = W_const() - margin - cw
    d.rounded_rectangle(
        [cx - pad, pill_y, cx + cw + pad, pill_y + pill_h],
        radius=pill_h // 2, fill=(0, 0, 0, 180),
    )
    d.text((cx, pill_y + (pill_h - (cb[3] - cb[1])) // 2 - cb[1]),
           counter, font=counter_font, fill=SOFT_WHITE)


def W_const() -> int:
    # Helper so the footer drawer doesn't have to plumb image dimensions
    # through every call — the carousel size is fixed at the topic level.
    return 1080


def _draw_slide(img: Image.Image, slot: dict, topic: TopicConfig,
                slide_num: int, total: int) -> None:
    """Dispatch to the per-kind renderer."""
    kind = slot.get("kind", "bait")
    if kind == "cover":
        _draw_cover_slide(img, slot, topic, slide_num, total)
    elif kind == "bait":
        _draw_bait_slide(img, slot, topic, slide_num, total)
    elif kind == "reveal":
        _draw_reveal_slide(img, slot, topic, slide_num, total)
    elif kind == "cta":
        _draw_cta_slide(img, slot, topic, slide_num, total)
    else:
        # Backward-compatible fallback for any legacy callers — treat
        # unknown kinds as a "bait" slide.
        _draw_bait_slide(img, slot, topic, slide_num, total)


# ── public render ─────────────────────────────────────────────────────────


def _today_label() -> str:
    """e.g. 'TUE · MAY 15' — short date stamp used as the cover eyebrow.
    Calibrated for adds-urgency / freshness signal, not absolute precision."""
    import datetime
    now = datetime.datetime.now()
    return now.strftime("%a · %b %d").upper()


def render(topic: TopicConfig, articles: list[Article],
           output_dir: Path) -> list[str]:
    """Cover hook + 3 stories × 2-slide pairs + save-bait CTA = 8 slides.

    Structure tuned for the 2026 IG/TikTok carousel algorithm:
      - Slide 1 (cover):     thumbstop hook + photo-stack recap +
                             today's date. Earns the swipe — saves
                             and shares depend on it.
      - Slides 2..7:         3 bait→reveal story pairs.
      - Slide 8 (save-bait): photo-stack backdrop + 'SAVE THIS' copy +
                             DM-share micro-CTA. Each save is worth
                             ~10 likes / each DM share ~15 likes in
                             the 2026 ranking model.

    Pairs are built from the top-N articles that have usable hero
    photos. If fewer than `PAIRS` articles qualify, the carousel
    shrinks to fit whatever pool we got.
    """
    if not articles:
        return []
    output_dir.mkdir(parents=True, exist_ok=True)
    img_dir = output_dir / "_images"

    with_photo = [a for a in articles if a.image_url]
    if len(with_photo) < PAIRS:
        with_photo = articles[:PAIRS]
    selected = with_photo[:PAIRS]

    local_imgs = download_images_parallel(
        [a.image_url or None for a in selected], img_dir,
    )

    W, H = topic.carousel.width, topic.carousel.height
    pair_w = W * SLIDES_PER_PAIR
    n_pairs = len(selected)
    n_total = 1 + n_pairs * SLIDES_PER_PAIR + 1  # cover + pairs + cta

    paths: list[str] = []

    # ── Slide 1: COVER ────────────────────────────────────────────────────
    # The thumbstop. 2026 algo data: cover slide drives ~80% of the
    # carousel's reach via swipe-through rate.
    cover_tile = _build_photo_stack_backdrop(topic, list(local_imgs), W, H)
    topic_label = (topic.display_name or topic.slug).upper()
    if topic.aggregate_from:
        # Sports Digest etc. — the meta-topic gets a count-led hook.
        cover_hook = f"{n_pairs} STORIES\nBLOWING UP IN\nSPORTS RIGHT NOW"
    else:
        cover_hook = f"TODAY'S TOP\n{n_pairs} {topic_label}\nSTORIES"
    cover_slot = {
        "kind": "cover",
        "text": cover_hook,
        "subtext": "Swipe through · save for later · send to a mate",
        "eyebrow": _today_label(),
    }
    _draw_slide(cover_tile, cover_slot, topic, 1, n_total)
    out = output_dir / f"slide_1.png"
    cover_tile.save(out, "PNG", quality=92)
    paths.append(str(out))
    log.info("  slide 1/%d · cover", n_total)

    # ── Slides 2..N-1: PAIRS ──────────────────────────────────────────────
    for pair_idx, (art, photo) in enumerate(zip(selected, local_imgs)):
        log.info("pair %d/%d · %s", pair_idx + 1, n_pairs, art.source)
        panorama = _build_panorama(photo, pair_w, H)
        slots = _plan_pair(art, pair_idx + 1, n_pairs)
        for sub in range(SLIDES_PER_PAIR):
            # +2 because slide 1 is the cover; pair slides start at 2
            slide_num = 1 + pair_idx * SLIDES_PER_PAIR + sub + 1
            tile = panorama.crop((sub * W, 0, (sub + 1) * W, H))
            _draw_slide(tile, slots[sub], topic, slide_num, n_total)
            out = output_dir / f"slide_{slide_num}.png"
            tile.save(out, "PNG", quality=92)
            paths.append(str(out))
            log.info("  slide %d/%d · %s", slide_num, n_total, slots[sub]["kind"])

    # ── Slide N: SAVE-BAIT CTA ────────────────────────────────────────────
    # Save (~10× a like) + DM-share (~15× a like) are the dominant
    # ranking signals in 2026. The copy here lands on both.
    cta_tile = _build_photo_stack_backdrop(topic, list(local_imgs), W, H)
    cta_slot = {
        "kind": "cta",
        "text": "SAVE THIS\nFOR LATER",
        # Bullets render with the system colour-emoji font. Falls back
        # to a plain → arrow if no emoji font is present.
        "bullets": [
            ("💾", "Save for the next watercooler talk"),
            ("📤", "Send to the friend who missed it"),
        ],
        "eyebrow": "TODAY'S DIGEST · " + topic_label,
    }
    _draw_slide(cta_tile, cta_slot, topic, n_total, n_total)
    out = output_dir / f"slide_{n_total}.png"
    cta_tile.save(out, "PNG", quality=92)
    paths.append(str(out))
    log.info("  slide %d/%d · save-bait cta", n_total, n_total)

    return paths


seamless = Design(
    slug="seamless",
    name="Seamless Panorama",
    description=(
        "Cover hook + three stories paired across 2-slide bait→reveal "
        "panoramas + save-bait outro (8 slides total). Tuned for the "
        "2026 IG/TikTok algorithm: the cover earns the swipe, each "
        "pair teases on slide A then pays off on slide B with the "
        "same photo darkened to a backdrop, and the closer asks for "
        "a save + DM share — the two signals that carry the most "
        "weight in 2026 distribution."
    ),
    render=render,
)

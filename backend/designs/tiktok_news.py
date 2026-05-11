"""TikTok News design — close copy of the @f1newsflash visual language.

Structure (1080×1920, hard-locked to TikTok 9:16):
  - Top ~52% of the slide is the hero photo, smart-cropped + lightly punched
  - Soft 80px gradient fades the photo's bottom edge into pure black
  - A circular "kicker emblem" sits in the top-right corner (topic logo if
    available — falls back to a coloured disc with the topic initial)
  - A small red sentiment dot overlaps that emblem (! / ? / ✕ / “ / ⚠),
    chosen by `quality.news_icon` based on the article wording
  - Bottom half is pure black with a centred all-caps headline (Anton)
  - The 1-2 final significant words are highlighted in the topic accent
    (defaults to the brand red, falls back to a punchy `#E63946`)
  - A thin slide counter sits centred at the very bottom

Compared to the existing `newsflash` legacy design:
  * 9:16 instead of 4:5 (TikTok native aspect)
  * Aggressive punchy headline rewriter (`text.punchy`)
  * Sentiment dot driven by article phrasing
  * Per-source emblem in the corner
  * No CTA slide — every slide is a real news story (mirrors the
    @f1newsflash pattern where each post is just a stack of stories)
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from core.http import download_images_parallel
from core.image import darken_band_under_text, punch, smart_cover
from core.log import get_logger
from core.parsers.base import Article
from core.quality import emoji_font_path, news_emoji, news_icon
from core.text import accent_phrase, punchy
from core.topic_loader import TopicConfig
from core.typography import balanced_wrap

from designs.base import Design

log = get_logger("design.tiktok_news")

CORE_FONTS = Path(__file__).resolve().parent.parent / "core" / "assets" / "fonts"
HEADLINE_FONT = str(CORE_FONTS / "Anton-Regular.ttf")
# Footer labels (counter pill, "VIA SOURCE") use BebasNeue — small all-
# caps display font that visually reads as a tabloid tag, distinct from
# the headline's Anton.
BODY_FONT_DISPLAY = str(CORE_FONTS / "BebasNeue-Regular.ttf")

# Hard-locked TikTok-native canvas. Topics that ship a different
# carousel.width/height are intentionally ignored — this design *is*
# 1080×1920 by definition. If you want 4:5 use the legacy `newsflash`.
W, H = 1080, 1920
# 1080×700 photo region — chosen to match the og:image aspect ratio
# (1200×630, 1.9:1) closely so we crop ~10% horizontally and upscale
# by only 1.11×. Was 1080×1056 before, which forced 1.42× upscale and
# made every slide look soft. The resulting black bottom is taller and
# fits a bigger headline — feels closer to the @f1newsflash crop too.
PHOTO_H = 700
FADE_H = 60                     # tight fade — photo doesn't bleed into text
TEXT_TOP = PHOTO_H + 80
TEXT_BOTTOM = H - 130
SAFE_W = W - 120                # 60px side margins

BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
SOFT_WHITE = (235, 235, 235)
MUTED = (120, 120, 120)
DEFAULT_RED = (230, 57, 70)


# ── primitives ─────────────────────────────────────────────────────────────


def _font(path: str | None, size: int, fallback: str) -> ImageFont.FreeTypeFont:
    p = path if (path and os.path.exists(path)) else fallback
    try:
        return ImageFont.truetype(p, size)
    except OSError:
        return ImageFont.load_default()


def _hero_photo(photo_path: str | None) -> Image.Image:
    """Load + smart-crop + punch the article hero. Falls back to a flat
    dark band if the photo isn't available."""
    if not photo_path or not os.path.exists(photo_path):
        return Image.new("RGB", (W, PHOTO_H), (24, 24, 24))
    try:
        img = Image.open(photo_path).convert("RGB")
        img = smart_cover(img, W, PHOTO_H, prefer_top=True)
        img = punch(img)
        return img
    except Exception as e:
        log.warning("hero failed: %s", e)
        return Image.new("RGB", (W, PHOTO_H), (24, 24, 24))


def _fade_bottom_edge(img: Image.Image, photo: Image.Image, base_y: int = 0) -> None:
    """Paste `photo` onto `img` and fade its bottom 90px into pure black."""
    img.paste(photo, (0, base_y))
    fade = Image.new("RGBA", (W, FADE_H), (0, 0, 0, 0))
    fd = ImageDraw.Draw(fade)
    for y in range(FADE_H):
        a = int((y / FADE_H) ** 1.5 * 255)
        fd.line([(0, y), (W, y)], fill=(0, 0, 0, a))
    base = img.convert("RGBA")
    base.alpha_composite(fade, (0, base_y + photo.height - FADE_H))
    img.paste(base.convert("RGB"))


def _emblem(topic: TopicConfig) -> Image.Image:
    """Round badge for the top-right corner. Uses the topic logo if the
    PNG is available and reasonably square; otherwise paints a flat disc
    in the topic accent with the topic's initial letter on it."""
    diameter = 220
    canvas = Image.new("RGBA", (diameter, diameter), (0, 0, 0, 0))
    accent = topic.brand.accent or DEFAULT_RED

    logo_path = topic.brand.logo_path
    used_logo = False
    if logo_path and os.path.exists(logo_path):
        try:
            logo = Image.open(logo_path).convert("RGBA")
            ratio = max(diameter / logo.width, diameter / logo.height)
            nw, nh = int(logo.width * ratio), int(logo.height * ratio)
            logo = logo.resize((nw, nh), Image.LANCZOS)
            x0 = (nw - diameter) // 2
            y0 = (nh - diameter) // 2
            logo = logo.crop((x0, y0, x0 + diameter, y0 + diameter))
            mask = Image.new("L", (diameter, diameter), 0)
            ImageDraw.Draw(mask).ellipse([0, 0, diameter - 1, diameter - 1], fill=255)
            canvas.paste(logo, (0, 0), mask)
            used_logo = True
        except Exception as e:
            log.warning("emblem logo failed: %s", e)

    if not used_logo:
        d = ImageDraw.Draw(canvas)
        d.ellipse([0, 0, diameter - 1, diameter - 1], fill=accent + (255,))
        # Initial letter or first 2 chars
        label = (topic.display_name or topic.slug or "").strip().upper()
        label = label[:2] if len(label) <= 3 else label[:1]
        font = _font(HEADLINE_FONT, 130, HEADLINE_FONT)
        bb = font.getbbox(label)
        tw, th = bb[2] - bb[0], bb[3] - bb[1]
        d.text(((diameter - tw) / 2 - bb[0], (diameter - th) / 2 - bb[1] - 10),
               label, font=font, fill=WHITE)

    # White ring around the emblem so it sits cleanly on the photo.
    ring = ImageDraw.Draw(canvas)
    ring.ellipse([2, 2, diameter - 3, diameter - 3], outline=WHITE, width=4)
    return canvas


def _sentiment_dot(article: Article) -> Image.Image:
    """White disc with a colour emoji that matches the article mood.

    Sized to overlap the emblem at its bottom-right. Falls back to the
    legacy red ASCII-glyph dot if no colour-emoji font is available
    (e.g. minimal Linux container without Noto Color Emoji)."""
    diameter = 96
    canvas = Image.new("RGBA", (diameter, diameter), (0, 0, 0, 0))
    d = ImageDraw.Draw(canvas)

    emoji_path = emoji_font_path()
    if emoji_path is None:
        # Fallback: legacy red disc + ASCII glyph
        d.ellipse([0, 0, diameter - 1, diameter - 1], fill=DEFAULT_RED + (255,))
        d.ellipse([2, 2, diameter - 3, diameter - 3], outline=WHITE, width=3)
        font = _font(HEADLINE_FONT, 60, HEADLINE_FONT)
        symbol = news_icon(article)
        bb = font.getbbox(symbol)
        tw, th = bb[2] - bb[0], bb[3] - bb[1]
        d.text(((diameter - tw) / 2 - bb[0], (diameter - th) / 2 - bb[1] - 6),
               symbol, font=font, fill=WHITE)
        return canvas

    # White background disc with a thin dark ring — keeps the badge
    # visually separated from the topic emblem without fighting the
    # emoji's own colours.
    d.ellipse([0, 0, diameter - 1, diameter - 1], fill=WHITE + (255,))
    d.ellipse([2, 2, diameter - 3, diameter - 3], outline=(0, 0, 0, 255), width=2)

    # Apple Color Emoji only loads at native 160px. Render once on a
    # transparent buffer, then downscale into the disc.
    glyph = news_emoji(article)
    native = 160
    buf = Image.new("RGBA", (native, native), (0, 0, 0, 0))
    bd = ImageDraw.Draw(buf)
    try:
        ef = ImageFont.truetype(emoji_path, native)
        bd.text((0, 0), glyph, font=ef, embedded_color=True)
    except Exception as e:
        log.warning("emoji render failed (%s) — fallback ASCII", e)
        font = _font(HEADLINE_FONT, 60, HEADLINE_FONT)
        bd.text((30, 30), news_icon(article), font=font, fill=BLACK)

    target = diameter - 16  # ~80px emoji inside ~96px disc
    glyph_img = buf.resize((target, target), Image.LANCZOS)
    canvas.alpha_composite(glyph_img, ((diameter - target) // 2,
                                        (diameter - target) // 2))
    return canvas


def _draw_emblem(img: Image.Image, topic: TopicConfig, article: Article) -> None:
    emblem = _emblem(topic)
    em_x = W - emblem.width - 60
    em_y = 60
    img.paste(emblem, (em_x, em_y), emblem)
    dot = _sentiment_dot(article)
    dot_x = em_x + emblem.width - dot.width + 10
    dot_y = em_y + emblem.height - dot.height + 10
    img.paste(dot, (dot_x, dot_y), dot)


def _draw_headline(img: Image.Image, title: str, accent_color,
                   *, has_body: bool = False) -> int:
    """Render the all-caps headline. Returns the y-coordinate just below
    the last line so the caller can stack a kicker fact underneath.

    `has_body` reserves ~170px at the bottom for a tight 2-line kicker
    (the first sentence of the article description). The headline still
    leads visually — the kicker is a one-line news fact, not a paragraph.
    """
    title = punchy(title).upper()
    accent_words = accent_phrase(title)
    bottom_limit = TEXT_BOTTOM - 30
    if has_body:
        # Body kicker reservation kept for designs that opt in via
        # has_body=True. The default tiktok_news slide is now headline-
        # only so the headline gets the full available height.
        bottom_limit -= 170
    available_h = bottom_limit - TEXT_TOP
    max_lines = max(2, min(5, available_h // 130))

    chosen_font: ImageFont.FreeTypeFont | None = None
    chosen_lines: list[str] = []
    for size in (158, 144, 132, 120, 110, 100, 92, 84, 76, 68):
        f = ImageFont.truetype(HEADLINE_FONT, size)
        lines = balanced_wrap(title, f, max_w=SAFE_W, max_lines=max_lines)
        if not lines:
            continue
        widest = max(f.getbbox(ln)[2] - f.getbbox(ln)[0] for ln in lines)
        line_h = f.getbbox("Hg")[3] + 14
        if widest <= SAFE_W and line_h * len(lines) <= available_h and len(lines) <= max_lines:
            chosen_font, chosen_lines = f, lines
            break
    if chosen_font is None:
        chosen_font = ImageFont.truetype(HEADLINE_FONT, 60)
        chosen_lines = balanced_wrap(title, chosen_font, max_w=SAFE_W, max_lines=max_lines) or [title]

    line_h = chosen_font.getbbox("Hg")[3] + 14
    block_h = line_h * len(chosen_lines)
    y = TEXT_TOP + (available_h - block_h) // 2

    d = ImageDraw.Draw(img)
    for line in chosen_lines:
        # Render word-by-word so we can colour the accent words.
        words = line.split()
        # Recompute width with a trailing space between words
        space_w = chosen_font.getbbox(" ")[2] - chosen_font.getbbox(" ")[0]
        word_widths = [chosen_font.getbbox(w)[2] - chosen_font.getbbox(w)[0] for w in words]
        total = sum(word_widths) + space_w * max(0, len(words) - 1)
        x = (W - total) // 2
        for idx, w in enumerate(words):
            clean = w.strip(",.!?\"'():;-")
            color = accent_color if clean.upper() in accent_words else WHITE
            # subtle drop shadow keeps the text readable if the gradient
            # didn't fully clean a residual colour fringe
            d.text((x + 2, y + 2), w, font=chosen_font, fill=BLACK)
            d.text((x, y), w, font=chosen_font, fill=color)
            x += word_widths[idx] + space_w
        y += line_h
    return y


def _draw_footer(img: Image.Image, slide_num: int, total: int,
                 source: str, accent_color) -> None:
    d = ImageDraw.Draw(img)
    # Footer labels use the display font (BebasNeue) so the small upper-
    # case tags keep the tabloid look while the body summary above stays
    # in Inter for readability.
    counter_font = _font(BODY_FONT_DISPLAY, 38, BODY_FONT_DISPLAY)
    txt = f"{slide_num} / {total}"
    bb = counter_font.getbbox(txt)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    pad_x, pad_y = 22, 10
    pw, ph = tw + pad_x * 2, th + pad_y * 2
    px = (W - pw) // 2
    py = H - ph - 60
    d.rounded_rectangle([px, py, px + pw, py + ph],
                        radius=ph // 2, outline=(80, 80, 80), width=2)
    d.text((px + pad_x - bb[0], py + pad_y - bb[1] - 4), txt,
           font=counter_font, fill=SOFT_WHITE)

    # Source attribution above the counter
    src_font = _font(BODY_FONT_DISPLAY, 30, BODY_FONT_DISPLAY)
    src = f"VIA {source.upper()}"
    sb = src_font.getbbox(src)
    sx = (W - (sb[2] - sb[0])) // 2
    d.text((sx, py - 50), src, font=src_font, fill=MUTED)


# ── public render ──────────────────────────────────────────────────────────


def _slide(article: Article, photo_path: str | None,
           slide_num: int, total: int, topic: TopicConfig,
           output_dir: Path) -> str:
    accent = topic.brand.accent or DEFAULT_RED
    img = Image.new("RGB", (W, H), BLACK)

    photo = _hero_photo(photo_path)
    _fade_bottom_edge(img, photo)

    _draw_emblem(img, topic, article)

    # Auto-readability scrim under the headline (cheap win — the bottom
    # half is pure black anyway, but if a future variant overlays text
    # on a photo this still works).
    darken_band_under_text(img, (0, TEXT_TOP - 20, W, TEXT_BOTTOM + 20),
                           threshold=120.0)
    # @f1newsflash style: each slide is photo + punchy headline + source.
    # The headline IS the news — body summaries that just paraphrase the
    # title made slides read like article previews instead of viral
    # news posts. The headline gets the full text region.
    _draw_headline(img, article.title, accent, has_body=False)
    _draw_footer(img, slide_num, total, article.source, accent)

    out_path = output_dir / f"slide_{slide_num}.png"
    img.save(out_path, "PNG", quality=95)
    return str(out_path)


def render(topic: TopicConfig, articles: list[Article],
           output_dir: Path) -> list[str]:
    """One slide per article — no hook, no CTA. The whole carousel is
    a stack of stories, exactly like the @f1newsflash feed."""
    output_dir.mkdir(parents=True, exist_ok=True)
    img_dir = output_dir / "_images"
    local_imgs = download_images_parallel(
        [a.image_url or None for a in articles], img_dir,
    )
    total = len(articles)
    paths: list[str] = []
    for i, (art, local) in enumerate(zip(articles, local_imgs), start=1):
        log.info("slide %d/%d · %s", i, total, art.source)
        paths.append(_slide(art, local, i, total, topic, output_dir))
    return paths


tiktok_news = Design(
    slug="tiktok_news",
    name="TikTok News",
    description=(
        "Close copy of the @f1newsflash visual language. 1080×1920, "
        "photo on top half, bold black-bottom headline with last words in "
        "red, circular topic emblem with a sentiment dot in the corner. "
        "One slide per story, no CTA."
    ),
    render=render,
)

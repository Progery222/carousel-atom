"""Slide engine. Renders 1080×1350 (4:5) PNGs.

Visual language modeled after @f1newsflash on TikTok:
  - Pure black background
  - Full-bleed photo top, fading to black
  - Massive Anton headline, bottom-anchored
  - Last 1-2 significant words highlighted in red
  - Thin divider + small circular brand mark as footer

Carousel structure:  N news + 1 CTA  (no separate hook slide).
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from core.http import download_images_parallel
from core.image import darken_band_under_text, smart_cover
from core.quality import emoji_font_path, news_emoji, news_icon
from core.log import get_logger
from core.parsers.base import Article
from core.topic_loader import TopicConfig

log = get_logger("design.newsflash")

# Fonts live under `backend/core/assets/fonts/`. The original path here
# pointed at a `designs/assets/fonts/` directory that was never created,
# so on real installs `_load_font` was silently falling back to Impact.
# Wiring through `core/assets/...` brings Anton + Bebas back, which is
# the type the rest of the design system was tuned against.
CORE_FONTS = Path(__file__).resolve().parent.parent / "core" / "assets" / "fonts"
HEADLINE_FONT = str(CORE_FONTS / "Anton-Regular.ttf")
BODY_FONT = str(CORE_FONTS / "BebasNeue-Regular.ttf")

BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
RED = (230, 57, 70)            # #E63946 — newsflash accent

SKIP_WORDS = {
    "THE", "A", "AN", "IS", "IN", "ON", "AT", "TO", "FOR", "OF",
    "AND", "OR", "BUT", "WITH", "FROM", "BY", "AS", "IT", "ITS", "IT'S",
    "HAS", "HAD", "HAVE", "ARE", "WAS", "WERE", "WILL", "ALL",
    "HOW", "WHAT", "WHEN", "WHO", "WHY", "THAT", "THIS", "THAN",
    "NOW", "JUST", "EVEN", "STILL", "SO", "BE", "BEEN", "DO", "DOES",
    "AFTER", "BEFORE", "OVER", "INTO", "OUT", "UP", "DOWN",
}


# ── Helpers ──────────────────────────────────────────────────────────────────

def _load_font(path: str | None, size: int, fallback: str = HEADLINE_FONT) -> ImageFont.FreeTypeFont:
    p = path if (path and os.path.exists(path)) else fallback
    try:
        return ImageFont.truetype(p, size)
    except (OSError, TypeError):
        try:
            return ImageFont.truetype("/System/Library/Fonts/Supplemental/Impact.ttf", size)
        except OSError:
            return ImageFont.load_default()


def _strip(w: str) -> str:
    return w.strip(",.!?\":();'-")


def _accent_phrase(title: str) -> set[str]:
    """Pick last 1-2 significant words to highlight as the punchline."""
    words = title.split()
    cleaned = [_strip(w).upper() for w in words]
    result: set[str] = set()
    count = 0
    for c in reversed(cleaned):
        if not c:
            continue
        if c in SKIP_WORDS:
            if count > 0:
                break
            continue
        result.add(c)
        count += 1
        if count >= 2:
            break
    return result


def _wrap_lines(font: ImageFont.FreeTypeFont, text: str, max_width: int) -> list[list[str]]:
    words = text.upper().split()
    lines: list[list[str]] = []
    current: list[str] = []
    for word in words:
        test = " ".join(current + [word])
        if font.getbbox(test)[2] - font.getbbox(test)[0] > max_width and current:
            lines.append(current)
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(current)
    return lines


def _fit_headline(text: str, max_width: int, max_lines: int,
                  sizes: tuple[int, ...] = (155, 135, 118, 102, 88, 76, 68, 60)
                  ) -> tuple[ImageFont.FreeTypeFont, list[list[str]], int]:
    """Pick the largest font that fits the title within `max_lines` rows,
    preferring the *fewest* lines possible.

    Strategy: try target=3 first (visually compact). If no size fits even
    at the smallest, allow 4. Then 5 (up to `max_lines`). This keeps short
    titles tight (3 lines, big photo visible) while still letting long
    titles expand without `…` truncation.
    """
    target_floor = min(3, max_lines)
    for target in range(target_floor, max_lines + 1):
        for size in sizes:
            font = _load_font(HEADLINE_FONT, size)
            lines = _wrap_lines(font, text, max_width)
            if len(lines) <= target:
                asc, desc = font.getmetrics()
                return font, lines, asc + desc
    font = _load_font(HEADLINE_FONT, sizes[-1])
    lines = _wrap_lines(font, text, max_width)[:max_lines]
    if lines:
        last = " ".join(lines[-1])
        if not last.endswith("…"):
            lines[-1] = (last + "…").split()
    asc, desc = font.getmetrics()
    return font, lines, asc + desc


def _draw_headline(draw, font, lines, area_x: int, area_w: int,
                   y_start: int, line_h: int, accent_words: set[str],
                   accent_color: tuple[int, int, int] = RED,
                   line_spacing: int = 4) -> None:
    """White headline; accent_words rendered in `accent_color`. Left-aligned."""
    y = y_start
    for line_words in lines:
        cx = area_x
        for word in line_words:
            clean = _strip(word).upper()
            color = accent_color if clean in accent_words else WHITE
            draw.text((cx + 2, y + 2), word, font=font, fill=(0, 0, 0))
            draw.text((cx, y), word, font=font, fill=color)
            wb = font.getbbox(word + " ")
            cx += wb[2] - wb[0]
        y += line_h + line_spacing


# Image downloads are delegated to `core.http`; kept as a thin alias so
# any external callers of `_download_image` keep working.
def _download_image(url: str, save_dir: Path) -> str | None:
    from core.http import _download_one
    return _download_one(url, save_dir)


def _paste_photo_region(img: Image.Image, image_path: str,
                        x: int, y: int, w: int, h: int) -> None:
    photo = Image.open(image_path).convert("RGB")
    photo = smart_cover(photo, w, h, prefer_top=True)
    img.paste(photo, (x, y))


def _fade_to_black(img: Image.Image, top: int, height: int,
                   curve: float = 1.5, direction: str = "down") -> None:
    """Vertical fade overlay → pure black.

    direction='down' — opaque at bottom (default, for top-mounted photo)
    direction='up'   — opaque at top    (for bottom-mounted photo)
    """
    W = img.width
    fade = Image.new("RGBA", (W, height), (0, 0, 0, 0))
    fd = ImageDraw.Draw(fade)
    for y in range(height):
        p = y / height if direction == "down" else 1 - y / height
        a = int(p ** curve * 255)
        fd.line([(0, y), (W, y)], fill=(0, 0, 0, a))
    img.paste(fade, (0, top), fade)


def _draw_progress_bar(img: Image.Image, current: int, total: int) -> None:
    """Segmented slide indicator. Active segment white, others muted.

    Drawn on a faint dark shadow strip so it stays readable when overlaid
    on a photo (e.g. the CTA slide).
    """
    W, H = img.size
    bar_y = H - 105
    bar_h = 6
    margin = 70
    gap = 8
    available_w = W - margin * 2
    seg_w = (available_w - gap * (total - 1)) / total
    radius = bar_h // 2

    shadow_pad_x = 14
    shadow_pad_y = 8
    shadow = Image.new(
        "RGBA",
        (available_w + shadow_pad_x * 2, bar_h + shadow_pad_y * 2),
        (0, 0, 0, 0),
    )
    sd = ImageDraw.Draw(shadow)
    sd.rounded_rectangle(
        [0, 0, shadow.width - 1, shadow.height - 1],
        radius=10,
        fill=(0, 0, 0, 110),
    )
    img.paste(shadow, (margin - shadow_pad_x, bar_y - shadow_pad_y), shadow)

    draw = ImageDraw.Draw(img)
    for i in range(total):
        x = margin + i * (seg_w + gap)
        color = WHITE if i == current else (160, 160, 160)
        draw.rounded_rectangle(
            [x, bar_y, x + seg_w, bar_y + bar_h],
            radius=radius,
            fill=color,
        )


def _draw_sentiment_dot(img: Image.Image, article: Article,
                        accent: tuple[int, int, int]) -> None:
    """Small badge in the top-right of the photo region. Picks a colour
    emoji that matches the article's mood (😢 / 🚨 / 🏆 / …) and renders
    it on a clean white disc. Falls back to the legacy red ASCII-glyph
    style if no colour-emoji font is available on the host."""
    diameter = 96
    canvas = Image.new("RGBA", (diameter, diameter), (0, 0, 0, 0))
    d = ImageDraw.Draw(canvas)

    emoji_path = emoji_font_path()
    if emoji_path is None:
        # Legacy fallback — keeps slides usable on hosts without a
        # colour-emoji font (minimal Linux containers etc).
        d.ellipse([0, 0, diameter - 1, diameter - 1], fill=RED + (255,))
        d.ellipse([3, 3, diameter - 4, diameter - 4], outline=WHITE, width=3)
        font = _load_font(HEADLINE_FONT, 60)
        symbol = news_icon(article)
        bb = font.getbbox(symbol)
        tw, th = bb[2] - bb[0], bb[3] - bb[1]
        d.text(((diameter - tw) / 2 - bb[0],
                (diameter - th) / 2 - bb[1] - 6),
               symbol, font=font, fill=WHITE)
        img.paste(canvas, (img.width - diameter - 50, 50), canvas)
        return

    d.ellipse([0, 0, diameter - 1, diameter - 1], fill=WHITE + (255,))
    d.ellipse([3, 3, diameter - 4, diameter - 4], outline=(0, 0, 0, 255), width=2)

    glyph = news_emoji(article)
    native = 160
    buf = Image.new("RGBA", (native, native), (0, 0, 0, 0))
    bd = ImageDraw.Draw(buf)
    try:
        ef = ImageFont.truetype(emoji_path, native)
        bd.text((0, 0), glyph, font=ef, embedded_color=True)
    except Exception as e:
        log.warning("emoji render failed (%s) — fallback ASCII", e)
        font = _load_font(HEADLINE_FONT, 60)
        bd.text((30, 30), news_icon(article), font=font, fill=BLACK)

    target = diameter - 16
    glyph_img = buf.resize((target, target), Image.LANCZOS)
    canvas.alpha_composite(glyph_img, ((diameter - target) // 2,
                                       (diameter - target) // 2))
    img.paste(canvas, (img.width - diameter - 50, 50), canvas)


def _draw_footer(img: Image.Image, label: str) -> None:
    """Centered display-name text in the same headline font as the slides."""
    W, H = img.size
    draw = ImageDraw.Draw(img)
    text = label.upper()
    font = _load_font(HEADLINE_FONT, 38)
    bb = font.getbbox(text)
    tw = bb[2] - bb[0]
    x = (W - tw) // 2 - bb[0]
    y = H - 70
    draw.text((x + 1, y + 1), text, font=font, fill=(0, 0, 0))
    draw.text((x, y), text, font=font, fill=WHITE)


# ── Templates ────────────────────────────────────────────────────────────────

def _make_news_slide(article: Article, image_path: str | None, slide_num: int,
                     total: int, topic: TopicConfig, output_dir: Path) -> str:
    """News slide — full-bleed photo top, bold bottom headline, footer."""
    W, H = topic.carousel.width, topic.carousel.height
    brand = topic.brand
    img = Image.new("RGB", (W, H), BLACK)

    # Photo region is 47% of the slide height (was 66%). New ratio
    # matches og:image's 1.9:1 closely — we crop ~10% horizontally and
    # the resize from 1077×630 to 1080×630 is essentially a no-op,
    # preserving JPEG sharpness instead of softening it through a 1.4×
    # upscale. The text region below is now 53% of the slide, which
    # comfortably fits 4–5 lines of bigger headline type.
    photo_h = int(H * 0.47)
    if image_path and os.path.exists(image_path):
        try:
            _paste_photo_region(img, image_path, 0, 0, W, photo_h)
        except Exception as e:
            log.warning("photo error: %s", e)

    # Just a tiny seam-fade now that there's a real black region below.
    fade_h = int(H * 0.06)
    _fade_to_black(img, top=photo_h - fade_h, height=fade_h, curve=2.2)

    # Sentiment dot in the top-right of the photo region: ! for breaking,
    # ? for rumour, X for denial, " for direct quote.
    _draw_sentiment_dot(img, article, brand.accent)

    draw = ImageDraw.Draw(img)

    margin = 60
    max_width = W - margin * 2
    safe_top = photo_h + 50
    safe_bottom = H - 130

    # Headline-only slide (matches tiktok_news). The body summary used
    # to live below the headline, but it ended up paraphrasing the
    # title and made each slide read like an article excerpt rather
    # than a viral news post. The headline now owns the full text region.
    available_h = safe_bottom - safe_top
    max_lines = max(2, min(5, available_h // 96))
    font, lines, line_h = _fit_headline(article.title, max_width, max_lines)

    # `_fit_headline` only enforces width; if the chosen font is too tall
    # for the available vertical room, drop a font-size step until it fits.
    text_h = len(lines) * (line_h + 4)
    while text_h > available_h and font.size > 50:
        font = _load_font(HEADLINE_FONT, max(50, int(font.size * 0.85)))
        lines = _wrap_lines(font, article.title, max_width)[:max_lines]
        asc, desc_ = font.getmetrics()
        line_h = asc + desc_
        text_h = len(lines) * (line_h + 4)

    accent = _accent_phrase(article.title)
    headline_y = safe_top + 10
    darken_band_under_text(
        img,
        (margin // 2, headline_y - 20, W - margin // 2, headline_y + text_h + 20),
    )
    _draw_headline(draw, font, lines, margin, max_width, headline_y,
                   line_h, accent, accent_color=brand.accent)

    _draw_progress_bar(img, slide_num, total)
    _draw_footer(img, topic.display_name)

    out_path = output_dir / f"slide_{slide_num + 1}.png"
    img.save(out_path, "PNG", quality=95)
    return str(out_path)


def _draw_brand_disc(img: Image.Image, topic: TopicConfig,
                     center_y: int, diameter: int = 360) -> None:
    """Centered "logo placeholder" for CTA slides.

    If `topic.brand.logo_path` points to an existing PNG we paste it (cropped
    to a circle, with a thin white ring). Otherwise we draw a flat disc in the
    topic accent colour with the topic's initial — gives every topic a usable
    CTA slide today, and the same code path will pick up real logos the
    moment a `logo:` is added to the topic's YAML.
    """
    W = img.width
    cx = W // 2

    disc = Image.new("RGBA", (diameter, diameter), (0, 0, 0, 0))
    used_logo = False
    logo_path = topic.brand.logo_path
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
            disc.paste(logo, (0, 0), mask)
            used_logo = True
        except Exception as e:
            log.warning("cta logo failed: %s", e)

    if not used_logo:
        d = ImageDraw.Draw(disc)
        d.ellipse([0, 0, diameter - 1, diameter - 1],
                  fill=topic.brand.accent + (255,))
        # Flat disc with the topic's initial — placeholder until a real logo
        # is dropped into `topic/<slug>/assets/logo.png`. We go through
        # `_load_font` so we get the same Impact-fallback chain the rest of
        # the design uses (the bundled Anton path is wrong on this legacy
        # file, but Impact ships with macOS and works fine).
        label = (topic.display_name or topic.slug or "").strip().upper()
        label = label[:1] if label else "·"
        font = _load_font(HEADLINE_FONT, int(diameter * 0.55))
        bb = font.getbbox(label)
        tw, th = bb[2] - bb[0], bb[3] - bb[1]
        d.text(((diameter - tw) / 2 - bb[0],
                (diameter - th) / 2 - bb[1] - int(diameter * 0.04)),
               label, font=font, fill=WHITE)

    # Thin white ring around the disc.
    ring = ImageDraw.Draw(disc)
    ring.ellipse([2, 2, diameter - 3, diameter - 3], outline=WHITE, width=4)

    img.paste(disc, (cx - diameter // 2, center_y - diameter // 2), disc)


def _make_cta_slide(slide_num: int, total: int, topic: TopicConfig,
                    output_dir: Path, hero_image: str | None = None) -> str:
    """CTA slide.

    Used to be the same shape as a news slide (full-bleed photo top +
    headline bottom). That recycled the article hero photo, which looked
    awkward on the very last slide ("FOLLOW FOR DAILY SOCCER NEWS" pinned
    over a player's face).

    New layout: pure black background, centred topic emblem (or its
    placeholder when no logo is shipped yet), headline beneath.
    `hero_image` is intentionally ignored.
    """
    del hero_image  # explicitly unused — kept for backward signature
    W, H = topic.carousel.width, topic.carousel.height
    brand = topic.brand
    img = Image.new("RGB", (W, H), BLACK)

    # Brand disc — sits a bit above the upper-third so it doesn't crowd
    # the headline that lands in the lower half.
    disc_y = int(H * 0.24)
    disc_diameter = int(min(W, H) * 0.30)
    _draw_brand_disc(img, topic, center_y=disc_y, diameter=disc_diameter)

    draw = ImageDraw.Draw(img)

    margin = 60
    max_width = W - margin * 2
    safe_bottom = H - 130

    raw = topic.cta.headline.replace("\n", " ").strip()
    max_lines = 4
    font, lines, line_h = _fit_headline(raw, max_width, max_lines)
    accent_words = {_strip(w).upper() for w in lines[-1]} if lines else set()
    text_h = len(lines) * (line_h + 4)
    headline_y = safe_bottom - text_h
    _draw_headline(draw, font, lines, margin, max_width, headline_y,
                   line_h, accent_words, accent_color=brand.accent)

    _draw_progress_bar(img, slide_num, total)
    _draw_footer(img, topic.display_name)

    out_path = output_dir / f"slide_{slide_num + 1}.png"
    img.save(out_path, "PNG", quality=95)
    return str(out_path)


# ── Public API ───────────────────────────────────────────────────────────────

def render_carousel(topic: TopicConfig, articles: list[Article],
                    output_dir: Path) -> list[str]:
    """N news + 1 CTA. Returns slide paths."""
    output_dir.mkdir(parents=True, exist_ok=True)
    img_dir = output_dir / "_images"
    total = len(articles) + 1
    paths: list[str] = []

    local_images = download_images_parallel(
        [a.image_url or None for a in articles], img_dir,
    )

    for i, (art, local_img) in enumerate(zip(articles, local_images)):
        log.info("news %d/%d: %s", i + 1, total, art.title[:60])
        paths.append(_make_news_slide(art, local_img, i, total, topic, output_dir))

    log.info("cta %d/%d", total, total)
    paths.append(_make_cta_slide(total - 1, total, topic, output_dir,
                                 hero_image=local_images[0] if local_images else None))
    return paths

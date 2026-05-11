"""Quote Card design.

Each slide treats one article like a pull-quote:
  - small badge with the source name top-left
  - large opening quotation mark
  - the headline rendered as a serif-ish "quote"
  - byline / source attribution
  - segmented progress bar at the bottom

Uses the topic's `font_headline` for the quote and falls back to the
shared core fonts for body labels. Background is the topic accent_light
shade with a subtle photo overlay (15% opacity) so the topic feels
on-brand without competing with the text.
"""
from __future__ import annotations

import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from core.copy import cta_copy
from core.http import download_images_parallel
from core.image import smart_cover
from core.log import get_logger
from core.parsers.base import Article
from core.quality import severity_of
from core.text import clean_headline
from core.topic_loader import TopicConfig
from core.typography import fit_font

from designs.base import Design

log = get_logger("design.quote_card")

CORE_FONTS = Path(__file__).resolve().parent.parent / "core" / "assets" / "fonts"
FALLBACK_HEADLINE = str(CORE_FONTS / "Anton-Regular.ttf")
FALLBACK_BODY = str(CORE_FONTS / "BebasNeue-Regular.ttf")

WHITE = (255, 255, 255)
INK = (15, 15, 15)
INK_SOFT = (60, 60, 60)


def _font(path: str | None, size: int, fallback: str) -> ImageFont.FreeTypeFont:
    p = path if (path and os.path.exists(path)) else fallback
    try:
        return ImageFont.truetype(p, size)
    except OSError:
        return ImageFont.load_default()


def _photo_layer(photo_path: str | None, w: int, h: int, blur: int = 30,
                 darken: float = 0.55) -> Image.Image:
    if not photo_path or not os.path.exists(photo_path):
        return Image.new("RGB", (w, h), INK)
    try:
        img = Image.open(photo_path).convert("RGB")
        img = smart_cover(img, w, h, prefer_top=True)
        img = img.filter(ImageFilter.GaussianBlur(blur))
        overlay = Image.new("RGBA", (w, h), (0, 0, 0, int(255 * darken)))
        img = img.convert("RGBA")
        img.alpha_composite(overlay)
        return img.convert("RGB")
    except Exception as e:
        log.warning("photo layer failed: %s", e)
        return Image.new("RGB", (w, h), INK)


def _draw_centered(d, y, text, font, color, w):
    bb = font.getbbox(text)
    tw = bb[2] - bb[0]
    d.text(((w - tw) / 2, y), text, font=font, fill=color)


def _draw_progress(img: Image.Image, current: int, total: int) -> None:
    W, H = img.size
    bar_y = H - 90
    bar_h = 8
    margin = 80
    gap = 10
    avail = W - margin * 2
    seg_w = (avail - gap * (total - 1)) / total
    radius = bar_h // 2
    draw = ImageDraw.Draw(img, "RGBA")
    for i in range(total):
        x = margin + i * (seg_w + gap)
        color = (255, 255, 255, 230) if i == current else (255, 255, 255, 90)
        draw.rounded_rectangle([x, bar_y, x + seg_w, bar_y + bar_h],
                               radius=radius, fill=color)


def _quote_slide(article: Article, photo_path: str | None, slide_num: int,
                 total: int, topic: TopicConfig, output_dir: Path) -> str:
    W, H = topic.carousel.width, topic.carousel.height
    accent = topic.brand.accent
    accent_light = topic.brand.accent_light

    img = _photo_layer(photo_path, W, H, blur=40, darken=0.62)
    d = ImageDraw.Draw(img)

    # Source label / counter
    label_font = _font(topic.brand.font_body, 38, FALLBACK_BODY)
    d.text((80, 80), article.source.upper(), font=label_font, fill=accent_light)
    counter_font = _font(topic.brand.font_body, 38, FALLBACK_BODY)
    counter = f"{slide_num} / {total}"
    bb = counter_font.getbbox(counter)
    d.text((W - 80 - (bb[2] - bb[0]), 80), counter, font=counter_font,
           fill=(220, 220, 220))

    # Big opening quote glyph
    q_font = _font(topic.brand.font_headline, 380, FALLBACK_HEADLINE)
    d.text((60, 130), "“", font=q_font, fill=accent)

    # Headline as the quote
    title = clean_headline(article.title)
    headline_font_path = topic.brand.font_headline or FALLBACK_HEADLINE
    headline_font, lines = fit_font(
        headline_font_path, title,
        max_w=W - 160, max_size=92, min_size=46, max_lines=4,
    )
    line_h = headline_font.getbbox("Hg")[3] + 14
    block_h = line_h * len(lines)
    y = (H - block_h) // 2
    for ln in lines:
        bb = headline_font.getbbox(ln)
        tw = bb[2] - bb[0]
        d.text((80, y), ln, font=headline_font, fill=WHITE)
        # Soft underline to anchor each line
        d.line([(80, y + line_h - 4), (80 + tw, y + line_h - 4)],
               fill=(255, 255, 255, 60), width=1)
        y += line_h

    # Description ribbon
    if article.description:
        desc_font = _font(topic.brand.font_body, 40, FALLBACK_BODY)
        from core.typography import balanced_wrap
        desc_lines = balanced_wrap(article.description, desc_font,
                                   max_w=W - 200, max_lines=3)
        ribbon_y = y + 50
        for ln in desc_lines[:3]:
            d.text((80, ribbon_y), ln, font=desc_font, fill=(220, 220, 220))
            ribbon_y += 56

    # Footer brand stripe
    stripe_h = 6
    d.rectangle([(0, H - 12), (W, H - 12 + stripe_h)], fill=accent)

    _draw_progress(img, slide_num - 1, total)
    out = output_dir / f"slide_{slide_num}.png"
    img.save(out, "PNG", quality=95)
    return str(out)


def _intro_slide(topic: TopicConfig, hero_path: str | None,
                 total: int, output_dir: Path) -> str:
    W, H = topic.carousel.width, topic.carousel.height
    img = _photo_layer(hero_path, W, H, blur=60, darken=0.78)
    d = ImageDraw.Draw(img)
    title_font = _font(topic.brand.font_headline, 110, FALLBACK_HEADLINE)
    sub_font = _font(topic.brand.font_body, 46, FALLBACK_BODY)

    headline = topic.display_name.upper()
    _draw_centered(d, int(H * 0.42), headline, title_font, WHITE, W)
    _draw_centered(d, int(H * 0.50), "QUOTES OF THE DAY",
                   sub_font, topic.brand.accent_light, W)
    _draw_centered(d, int(H * 0.55),
                   "Five voices from the last 24 hours",
                   sub_font, (220, 220, 220), W)
    _draw_progress(img, 0, total)
    out = output_dir / "slide_1.png"
    img.save(out, "PNG", quality=95)
    return str(out)


def _outro_slide(topic: TopicConfig, hero_path: str | None,
                 slide_num: int, total: int, output_dir: Path,
                 *, tone: str = "viral") -> str:
    W, H = topic.carousel.width, topic.carousel.height
    img = _photo_layer(hero_path, W, H, blur=60, darken=0.8)
    d = ImageDraw.Draw(img)
    cta = cta_copy(topic, tone=tone)

    title_font = _font(topic.brand.font_headline, 130, FALLBACK_HEADLINE)
    body_font = _font(topic.brand.font_body, 50, FALLBACK_BODY)
    _draw_centered(d, int(H * 0.30), cta.q1, title_font, WHITE, W)
    _draw_centered(d, int(H * 0.40), cta.q2, title_font, WHITE, W)
    _draw_centered(d, int(H * 0.50), cta.q3, title_font, topic.brand.accent, W)
    _draw_centered(d, int(H * 0.65), cta.prompt1, body_font, (230, 230, 230), W)
    _draw_centered(d, int(H * 0.69), cta.prompt2, body_font, (230, 230, 230), W)
    _draw_centered(d, int(H * 0.82), "FOLLOW »",
                   _font(topic.brand.font_headline, 90, FALLBACK_HEADLINE),
                   topic.brand.accent_light, W)
    _draw_progress(img, slide_num - 1, total)
    out = output_dir / f"slide_{slide_num}.png"
    img.save(out, "PNG", quality=95)
    return str(out)


def render(topic: TopicConfig, articles: list[Article],
           output_dir: Path) -> list[str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    img_dir = output_dir / "_images"
    local_imgs = download_images_parallel(
        [a.image_url or None for a in articles], img_dir,
    )

    n = len(articles)
    total = n + 2
    paths: list[str] = []

    log.info("intro 1/%d", total)
    paths.append(_intro_slide(topic, local_imgs[0] if local_imgs else None,
                              total, output_dir))

    for i, (art, local) in enumerate(zip(articles, local_imgs), start=2):
        log.info("quote %d/%d", i, total)
        paths.append(_quote_slide(art, local, i, total, topic, output_dir))

    has_severe = any(severity_of(a) == "severe" for a in articles)
    log.info("outro %d/%d (tone=%s)", total, total,
             "severe" if has_severe else "viral")
    paths.append(_outro_slide(topic, local_imgs[0] if local_imgs else None,
                              total, total, output_dir,
                              tone="severe" if has_severe else "viral"))
    return paths


quote_card = Design(
    slug="quote_card",
    name="Quote Card",
    description=(
        "Editorial pull-quote treatment — soft blurred photo, large "
        "opening quote mark, balanced typography. Reads slower than "
        "Newsflash, better for long-form headlines and feature stories."
    ),
    render=render,
)

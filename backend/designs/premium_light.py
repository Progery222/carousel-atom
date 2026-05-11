"""Premium Light design.

A clean, magazine-style alternative to the all-dark default templates:
  - off-white background (#F5F2EC)
  - dark serif-style headline rendered with the topic's headline font
  - small monochrome thumbnail of the article photo (right side)
  - thin accent line above the headline
  - minimal footer with the topic name and slide counter

Intentionally avoids the "BREAKING / BLOWING UP" voice — this design is
for thoughtful summaries and lifestyle stories.
"""
from __future__ import annotations

import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from core.copy import cta_copy
from core.http import download_images_parallel
from core.image import smart_cover
from core.log import get_logger
from core.parsers.base import Article
from core.text import clean_headline
from core.topic_loader import TopicConfig
from core.typography import balanced_wrap, fit_font

from designs.base import Design

log = get_logger("design.premium_light")

CORE_FONTS = Path(__file__).resolve().parent.parent / "core" / "assets" / "fonts"
FALLBACK_HEADLINE = str(CORE_FONTS / "Anton-Regular.ttf")
FALLBACK_BODY = str(CORE_FONTS / "BebasNeue-Regular.ttf")

CREAM = (245, 242, 236)
INK = (20, 20, 20)
INK_SOFT = (90, 90, 90)


def _font(path: str | None, size: int, fallback: str) -> ImageFont.FreeTypeFont:
    p = path if (path and os.path.exists(path)) else fallback
    try:
        return ImageFont.truetype(p, size)
    except OSError:
        return ImageFont.load_default()


def _thumb(photo_path: str | None, w: int, h: int) -> Image.Image | None:
    if not photo_path or not os.path.exists(photo_path):
        return None
    try:
        img = Image.open(photo_path).convert("RGB")
        return smart_cover(img, w, h, prefer_top=True)
    except Exception as e:
        log.warning("thumb failed: %s", e)
        return None


def _news_slide(article: Article, photo_path: str | None, slide_num: int,
                total: int, topic: TopicConfig, output_dir: Path) -> str:
    W, H = topic.carousel.width, topic.carousel.height
    accent = topic.brand.accent

    img = Image.new("RGB", (W, H), CREAM)
    d = ImageDraw.Draw(img)

    # Header — small kicker with topic name + counter
    label_font = _font(topic.brand.font_body, 34, FALLBACK_BODY)
    d.text((80, 80), topic.display_name.upper(), font=label_font, fill=INK_SOFT)
    counter = f"{slide_num:02d} / {total:02d}"
    bb = label_font.getbbox(counter)
    d.text((W - 80 - (bb[2] - bb[0]), 80), counter, font=label_font, fill=INK_SOFT)

    # Accent line under the kicker
    d.line([(80, 132), (W - 80, 132)], fill=accent, width=4)

    # Hero thumbnail
    thumb_w = int(W * 0.62)
    thumb_h = int(H * 0.34)
    thumb = _thumb(photo_path, thumb_w, thumb_h)
    if thumb is not None:
        # Soft drop shadow
        shadow = Image.new("RGBA", (thumb_w + 24, thumb_h + 24), (0, 0, 0, 0))
        sd = ImageDraw.Draw(shadow)
        sd.rounded_rectangle([12, 12, thumb_w + 24, thumb_h + 24],
                             radius=14, fill=(0, 0, 0, 35))
        thumb_x = (W - thumb_w) // 2
        thumb_y = 200
        img.paste(shadow, (thumb_x - 12, thumb_y - 12), shadow)
        img.paste(thumb, (thumb_x, thumb_y))

    # Headline
    title = clean_headline(article.title)
    headline_path = topic.brand.font_headline or FALLBACK_HEADLINE
    headline_font, lines = fit_font(
        headline_path, title,
        max_w=W - 160, max_size=80, min_size=44, max_lines=3,
    )
    line_h = headline_font.getbbox("Hg")[3] + 12
    y = 200 + thumb_h + 70
    for ln in lines:
        d.text((80, y), ln, font=headline_font, fill=INK)
        y += line_h

    # Body summary — up to 3 lines so the slide reads as a complete
    # news item, not just a headline. Calm body font, ink-soft colour
    # so the headline still leads visually.
    if article.description:
        from core.text import clean_description
        desc = clean_description(article.description, max_chars=260)
        if desc:
            body_font = _font(topic.brand.font_body, 36, FALLBACK_BODY)
            body_lines = balanced_wrap(desc, body_font,
                                       max_w=W - 160, max_lines=3)[:3]
            body_line_h = body_font.getbbox("Hg")[3] + 8
            y += 24
            for ln in body_lines:
                d.text((80, y), ln, font=body_font, fill=INK_SOFT)
                y += body_line_h

    # Source pill + read-time-ish hint
    pill_font = _font(topic.brand.font_body, 32, FALLBACK_BODY)
    pill_text = article.source.upper()
    bb = pill_font.getbbox(pill_text)
    pill_w = (bb[2] - bb[0]) + 32
    pill_h = (bb[3] - bb[1]) + 18
    d.rounded_rectangle(
        [80, H - 170, 80 + pill_w, H - 170 + pill_h],
        radius=pill_h // 2, fill=accent,
    )
    d.text((80 + 16, H - 170 + 6), pill_text, font=pill_font, fill=CREAM)

    # Slide counter dots, anchored bottom-right
    dot_y = H - 170 + pill_h // 2
    dot_r = 6
    gap = 18
    total_w = total * (dot_r * 2) + (total - 1) * gap
    start_x = W - 80 - total_w
    for i in range(total):
        cx = start_x + i * (dot_r * 2 + gap) + dot_r
        col = INK if i == slide_num - 1 else (200, 200, 200)
        d.ellipse([(cx - dot_r, dot_y - dot_r), (cx + dot_r, dot_y + dot_r)],
                  fill=col)

    out = output_dir / f"slide_{slide_num}.png"
    img.save(out, "PNG", quality=95)
    return str(out)


def _intro_slide(topic: TopicConfig, total: int, output_dir: Path) -> str:
    W, H = topic.carousel.width, topic.carousel.height
    img = Image.new("RGB", (W, H), CREAM)
    d = ImageDraw.Draw(img)

    accent = topic.brand.accent
    d.line([(80, int(H * 0.36)), (W - 80, int(H * 0.36))], fill=accent, width=4)

    label_font = _font(topic.brand.font_body, 38, FALLBACK_BODY)
    d.text((80, int(H * 0.32) - 50), topic.display_name.upper(),
           font=label_font, fill=INK_SOFT)

    headline_path = topic.brand.font_headline or FALLBACK_HEADLINE
    big = ImageFont.truetype(headline_path, 130)
    headline = "TODAY'S\nBRIEFING"
    y = int(H * 0.42)
    for line in headline.split("\n"):
        d.text((80, y), line, font=big, fill=INK)
        y += big.getbbox("Hg")[3] + 12

    body = _font(topic.brand.font_body, 46, FALLBACK_BODY)
    bullet_lines = balanced_wrap(
        f"Five short stories shaping {topic.display_name.lower()} right now.",
        body, max_w=W - 160, max_lines=3,
    )
    by = int(H * 0.74)
    for ln in bullet_lines:
        d.text((80, by), ln, font=body, fill=INK_SOFT)
        by += 56

    out = output_dir / "slide_1.png"
    img.save(out, "PNG", quality=95)
    return str(out)


def _outro_slide(topic: TopicConfig, slide_num: int, total: int,
                 output_dir: Path, *, tone: str = "viral") -> str:
    W, H = topic.carousel.width, topic.carousel.height
    img = Image.new("RGB", (W, H), CREAM)
    d = ImageDraw.Draw(img)

    accent = topic.brand.accent
    cta = cta_copy(topic, tone=tone)
    headline_path = topic.brand.font_headline or FALLBACK_HEADLINE
    big = ImageFont.truetype(headline_path, 120)

    y = int(H * 0.32)
    for line in (cta.q1, cta.q2, cta.q3):
        color = accent if line is cta.q3 else INK
        d.text((80, y), line, font=big, fill=color)
        y += big.getbbox("Hg")[3] + 12

    body = _font(topic.brand.font_body, 48, FALLBACK_BODY)
    d.text((80, int(H * 0.70)), cta.prompt1, font=body, fill=INK_SOFT)
    d.text((80, int(H * 0.74)), cta.prompt2, font=body, fill=INK_SOFT)

    follow = ImageFont.truetype(headline_path, 100)
    d.text((80, int(H * 0.84)), "FOLLOW »", font=follow, fill=accent)

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
    paths: list[str] = [_intro_slide(topic, total, output_dir)]

    for i, (art, local) in enumerate(zip(articles, local_imgs), start=2):
        log.info("news %d/%d", i, total)
        paths.append(_news_slide(art, local, i, total, topic, output_dir))

    log.info("outro %d/%d", total, total)
    paths.append(_outro_slide(topic, total, total, output_dir))
    return paths


premium_light = Design(
    slug="premium_light",
    name="Premium Light",
    description=(
        "Magazine-style off-white layout. Calm typography, monochrome "
        "thumbnail, accent pill with the source. Built for lifestyle and "
        "feature stories where the loud dark templates feel out of place."
    ),
    render=render,
)

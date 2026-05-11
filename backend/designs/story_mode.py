"""Story Mode design — narrative carousel.

Visual language:
  - "Chapter X" kicker top-left (CHAPTER 01 / OF 05)
  - Hero photo full-bleed with smart crop, soft top→bottom dark gradient
  - One-line "story prompt" overlay on intro slide
  - Headline rendered as a one-sentence statement, not a tabloid hook
  - Footer line with topic name and pill-shaped slide counter
  - Severity-aware: if any article is heavy, intro/outro skip the playful
    "the story everyone is sleeping on" voice.

The tone is reflective rather than punchy — fits feature articles, longer
analyses, lifestyle stories. Pairs with `caption.style: thread` for the
caption side.
"""
from __future__ import annotations

import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from core.copy import cta_copy
from core.http import download_images_parallel
from core.image import darken_band_under_text, smart_cover
from core.log import get_logger
from core.parsers.base import Article
from core.quality import severity_of
from core.text import clean_description, clean_headline
from core.topic_loader import TopicConfig
from core.typography import fit_font

from designs.base import Design

log = get_logger("design.story_mode")

CORE_FONTS = Path(__file__).resolve().parent.parent / "core" / "assets" / "fonts"
FALLBACK_HEADLINE = str(CORE_FONTS / "Anton-Regular.ttf")
FALLBACK_BODY = str(CORE_FONTS / "BebasNeue-Regular.ttf")

WHITE = (255, 255, 255)
SOFT_WHITE = (235, 235, 235)
INK = (10, 10, 10)


def _font(path: str | None, size: int, fallback: str) -> ImageFont.FreeTypeFont:
    p = path if (path and os.path.exists(path)) else fallback
    try:
        return ImageFont.truetype(p, size)
    except OSError:
        return ImageFont.load_default()


def _hero(photo_path: str | None, w: int, h: int,
          *, gradient_strength: float = 0.55) -> Image.Image:
    if not photo_path or not os.path.exists(photo_path):
        return Image.new("RGB", (w, h), INK)
    try:
        img = Image.open(photo_path).convert("RGB")
        img = smart_cover(img, w, h, prefer_top=True)
        # Vertical fade — darker at the bottom where headline lives.
        gradient = Image.new("L", (1, h), 0)
        for y in range(h):
            t = y / max(1, h - 1)
            alpha = int((t ** 1.6) * 255 * gradient_strength)
            gradient.putpixel((0, y), alpha)
        gradient = gradient.resize((w, h))
        overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        overlay.putalpha(gradient)
        img = img.convert("RGBA")
        img.alpha_composite(overlay)
        return img.convert("RGB")
    except Exception as e:
        log.warning("hero failed: %s", e)
        return Image.new("RGB", (w, h), INK)


def _draw_chapter_label(d: ImageDraw.ImageDraw, slide_num: int, total_chapters: int,
                        font: ImageFont.FreeTypeFont, color=SOFT_WHITE) -> None:
    txt = f"CHAPTER {slide_num:02d} · OF {total_chapters:02d}"
    d.text((80, 80), txt, font=font, fill=color)


def _draw_pill_counter(img: Image.Image, slide_num: int, total: int,
                       accent: tuple[int, int, int]) -> None:
    W, H = img.size
    d = ImageDraw.Draw(img, "RGBA")
    txt = f"{slide_num} / {total}"
    font = _font(FALLBACK_BODY, 36, FALLBACK_BODY)
    bb = font.getbbox(txt)
    pad_x, pad_y = 22, 10
    pw = bb[2] - bb[0] + pad_x * 2
    ph = bb[3] - bb[1] + pad_y * 2
    px = W - 80 - pw
    py = H - 100 - ph
    d.rounded_rectangle([px, py, px + pw, py + ph], radius=ph // 2,
                        fill=(0, 0, 0, 130))
    d.text((px + pad_x, py + pad_y - bb[1]), txt, font=font, fill=accent)


def _collage_cover(topic: TopicConfig, photo_paths: list[str | None],
                   W: int, H: int) -> Image.Image:
    """2×3 tile of the article hero photos with the bottom-right cell
    painted in the brand accent. Acts as the cover slide so the intro
    no longer duplicates slide 2's photo. Photos fill 5 of 6 cells in
    reading order; the 6th cell anchors the title block. Falls back to
    a flat brand-bg cell when a photo is missing."""
    img = Image.new("RGB", (W, H), INK)
    cell_w = W // 2
    cell_h = H // 3
    accent = topic.brand.accent or (255, 24, 1)
    positions = [
        (0,      0),
        (cell_w, 0),
        (0,      cell_h),
        (cell_w, cell_h),
        (0,      cell_h * 2),
    ]
    available = [p for p in photo_paths if p and os.path.exists(p)][:5]
    for i, (x, y) in enumerate(positions):
        if i < len(available):
            try:
                photo = Image.open(available[i]).convert("RGB")
                photo = smart_cover(photo, cell_w, cell_h)
                img.paste(photo, (x, y))
            except Exception as e:
                log.warning("collage cell %d failed: %s", i, e)
    # Bottom-right cell = accent solid (anchors the title block)
    d0 = ImageDraw.Draw(img)
    d0.rectangle([cell_w, cell_h * 2, W, H], fill=accent)
    # Global darken so text on top reads cleanly across all photo cells
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 120))
    rgba = img.convert("RGBA")
    rgba.alpha_composite(overlay)
    return rgba.convert("RGB")


def _intro(topic: TopicConfig, photo_paths: list[str | None], total: int,
           total_chapters: int, output_dir: Path, *, severe: bool) -> str:
    W, H = topic.carousel.width, topic.carousel.height
    img = _collage_cover(topic, photo_paths, W, H)
    d = ImageDraw.Draw(img)

    chapter_font = _font(topic.brand.font_body, 38, FALLBACK_BODY)
    _draw_chapter_label(d, 1, total_chapters, chapter_font)

    headline_path = topic.brand.font_headline or FALLBACK_HEADLINE
    small = _font(topic.brand.font_body, 50, FALLBACK_BODY)

    line1 = topic.display_name.upper()
    line2 = "THE WEEK SO FAR" if severe else "TODAY'S STORY ARC"
    sub = (
        "Five stories we should not look away from."
        if severe
        else "Five threads worth pulling on right now."
    )
    # Auto-fit each headline line to the safe width — needed because the
    # collage cover sits behind text in arbitrary brand fonts (Inter,
    # Anton, Bebas …) that vary widely in advance width.
    safe_w = W - 160
    f1, _l1 = fit_font(headline_path, line1, safe_w,
                       max_size=130, min_size=70, max_lines=1)
    f2, _l2 = fit_font(headline_path, line2, safe_w,
                       max_size=130, min_size=70, max_lines=1)

    block_y = int(H * 0.55)
    line1_h = f1.getbbox("Hg")[3] + 14
    d.text((80, block_y), line1, font=f1, fill=WHITE)
    # White on the accent panel and on dimmed photos both read fine —
    # avoids accent-light bleeding into the red panel beneath "ARC".
    d.text((80, block_y + line1_h), line2, font=f2, fill=WHITE)
    d.text((80, block_y + line1_h + (f2.getbbox("Hg")[3] + 14) + 30),
           sub, font=small, fill=SOFT_WHITE)

    _draw_pill_counter(img, 1, total, topic.brand.accent_light)
    out = output_dir / "slide_1.png"
    img.save(out, "PNG", quality=95)
    return str(out)


def _chapter(article: Article, photo_path: str | None, slide_num: int,
             chapter_num: int, total_chapters: int, total: int,
             topic: TopicConfig, output_dir: Path) -> str:
    W, H = topic.carousel.width, topic.carousel.height
    img = _hero(photo_path, W, H, gradient_strength=0.6)
    d = ImageDraw.Draw(img)

    chapter_font = _font(topic.brand.font_body, 38, FALLBACK_BODY)
    _draw_chapter_label(d, chapter_num, total_chapters, chapter_font,
                        color=topic.brand.accent_light)

    title = clean_headline(article.title)
    headline_path = topic.brand.font_headline or FALLBACK_HEADLINE

    # 4-line body summary carries the actual news content — each slide
    # must read as a self-contained story, not a headline tease.
    body_text = clean_description(article.description or "", max_chars=300)
    has_body = bool(body_text and len(body_text) >= 15)

    # If we have body text, leave room for it underneath the headline by
    # constraining the headline to fewer/smaller lines.
    if has_body:
        headline_font, lines = fit_font(
            headline_path, title,
            max_w=W - 160, max_size=84, min_size=44, max_lines=3,
        )
    else:
        headline_font, lines = fit_font(
            headline_path, title,
            max_w=W - 160, max_size=98, min_size=44, max_lines=4,
        )
    line_h = headline_font.getbbox("Hg")[3] + 14
    block_h = line_h * len(lines)
    body_font = _font(topic.brand.font_body, 38, FALLBACK_BODY)
    body_lines: list[str] = []
    body_block_h = 0
    if has_body:
        from core.typography import balanced_wrap
        body_lines = balanced_wrap(body_text, body_font, max_w=W - 160, max_lines=4)
        body_line_h = body_font.getbbox("Hg")[3] + 8
        body_block_h = body_line_h * len(body_lines) + 30  # gap above body

    # Anchor the headline+body block at ~62% of canvas height, then pull
    # back so the combined block stays centred on that anchor.
    block_y = int(H * 0.62) - (block_h + body_block_h) // 2

    # Make sure the hero shot doesn't drown out the text region.
    darken_band_under_text(
        img,
        (40, block_y - 30, W - 40, block_y + block_h + body_block_h + 30),
        threshold=110.0,
    )
    for ln in lines:
        d.text((80, block_y), ln, font=headline_font, fill=WHITE)
        block_y += line_h

    if body_lines:
        block_y += 30  # breathing room between headline and body
        body_line_h = body_font.getbbox("Hg")[3] + 8
        for ln in body_lines:
            d.text((80, block_y), ln, font=body_font, fill=SOFT_WHITE)
            block_y += body_line_h

    # Source attribution
    src_font = _font(topic.brand.font_body, 38, FALLBACK_BODY)
    d.text((80, H - 175), f"VIA {article.source.upper()}",
           font=src_font, fill=SOFT_WHITE)

    _draw_pill_counter(img, slide_num, total, topic.brand.accent_light)
    out = output_dir / f"slide_{slide_num}.png"
    img.save(out, "PNG", quality=95)
    return str(out)


def _outro(topic: TopicConfig, hero_path: str | None, slide_num: int,
           total: int, output_dir: Path, *, tone: str = "viral") -> str:
    W, H = topic.carousel.width, topic.carousel.height
    img = _hero(hero_path, W, H, gradient_strength=0.78)
    d = ImageDraw.Draw(img)

    cta = cta_copy(topic, tone=tone)
    big = ImageFont.truetype(topic.brand.font_headline or FALLBACK_HEADLINE, 110)
    body = _font(topic.brand.font_body, 50, FALLBACK_BODY)

    y = int(H * 0.30)
    for line in (cta.q1, cta.q2, cta.q3):
        col = topic.brand.accent_light if line is cta.q3 else WHITE
        d.text((80, y), line, font=big, fill=col)
        y += big.getbbox("Hg")[3] + 12

    d.text((80, int(H * 0.66)), cta.prompt1, font=body, fill=SOFT_WHITE)
    d.text((80, int(H * 0.71)), cta.prompt2, font=body, fill=SOFT_WHITE)

    follow = ImageFont.truetype(topic.brand.font_headline or FALLBACK_HEADLINE, 100)
    d.text((80, int(H * 0.85)), "FOLLOW »", font=follow, fill=topic.brand.accent)

    _draw_pill_counter(img, slide_num, total, topic.brand.accent_light)
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
    severe = any(severity_of(a) == "severe" for a in articles)
    paths: list[str] = []

    log.info("intro 1/%d", total)
    paths.append(_intro(topic, local_imgs,
                        total, total_chapters=n, output_dir=output_dir, severe=severe))

    for i, (art, local) in enumerate(zip(articles, local_imgs)):
        slide_num = i + 2
        log.info("chapter %d/%d", slide_num, total)
        paths.append(_chapter(
            art, local, slide_num, chapter_num=i + 1,
            total_chapters=n, total=total, topic=topic, output_dir=output_dir,
        ))

    log.info("outro %d/%d (tone=%s)", total, total, "severe" if severe else "viral")
    paths.append(_outro(topic, local_imgs[0] if local_imgs else None,
                        total, total, output_dir,
                        tone="severe" if severe else "viral"))
    return paths


story_mode = Design(
    slug="story_mode",
    name="Story Mode",
    description=(
        "Narrative arc — chapter labels, dark vertical gradient, reflective "
        "tone. Built for feature stories and weekly recaps where the "
        "tabloid voice of Viral Roundup feels wrong."
    ),
    render=render,
)

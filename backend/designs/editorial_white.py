"""Editorial White design — Threads-style editorial carousel.

Visual reference: the @anastasiya_gozhenkina / @gloriwht Threads posts
the user shared as inspiration. The common visual language is:

  - White / off-white background, lots of breathable negative space
  - Huge sans-serif headline (3-4 lines) filling most of the slide
  - One line in a bright accent colour, others near-black
  - Sentence-case subtitle in muted gray below the headline
  - Hand-drawn brush stroke under (part of) the subtitle
  - Subject photo composited bottom-right with a soft radial fade
    into the white background — no hard edge, no frame
  - Discreet page counter, no chrome

  ┌────────────────────────────────┐
  │ ▸ SPORTS DIGEST                │  ← tiny brand chip top-left
  │                                │
  │  HUGE BLACK LINE 1             │
  │  HUGE ACCENT LINE 2            │  ← topic brand colour
  │  HUGE BLACK LINE 3             │
  │                                │
  │  subtitle in muted gray,       │
  │  wrapping to two lines  ───────│  ← brush stroke
  │                                │
  │                  ┌──────────┐  │
  │                  │  photo   │  │  ← soft-fade vignette to white
  │                  │          │  │
  │                  └──────────┘  │
  │                          01/05 │
  └────────────────────────────────┘
"""
from __future__ import annotations

import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from core import bg_remove
from core.http import download_images_parallel
from core.image import smart_cover
from core.log import get_logger
from core.parsers.base import Article
from core.text import clean_headline
from core.topic_loader import TopicConfig
from core.typography import fit_font

from designs.base import Design

log = get_logger("design.editorial_white")

CORE_FONTS = Path(__file__).resolve().parent.parent / "core" / "assets" / "fonts"
HEADLINE_FONT = str(CORE_FONTS / "Inter-Bold.ttf")
SUBTITLE_FONT = str(CORE_FONTS / "Inter-Bold.ttf")  # body text, smaller weight via size
COUNTER_FONT = str(CORE_FONTS / "BebasNeue-Regular.ttf")

W, H = 1080, 1350

BG = (250, 248, 244)        # warm off-white
INK = (18, 18, 22)           # near-black with subtle warmth
INK_MUTED = (118, 118, 124)  # subtitle gray
WHITE = (255, 255, 255)


# ── helpers ─────────────────────────────────────────────────────────────


def _accent_color(topic: TopicConfig) -> tuple[int, int, int]:
    """Pick a single accent colour from the topic brand. Used to recolour
    one line of the headline.
    """
    r, g, b = topic.brand.accent
    # Push slightly toward saturation so it pops on the off-white bg.
    # Black/very-dark accents (e.g. some topics use #0A0A0A) look like
    # the rest of the headline — bump to a known editorial pink instead.
    if max(r, g, b) < 60:
        return (235, 68, 124)  # editorial hot pink as a fallback
    return (r, g, b)


def _draw_brand_chip(d: ImageDraw.ImageDraw, topic: TopicConfig,
                     x: int, y: int) -> int:
    """Tiny ▸ + brand name at top-left. Returns the y-bottom of the chip."""
    chip_font = ImageFont.truetype(SUBTITLE_FONT, 22)
    label = (topic.display_name or topic.slug).upper()
    text = f"▸  {label}"
    bb = d.textbbox((x, y), text, font=chip_font)
    d.text((x, y), text, font=chip_font, fill=INK_MUTED)
    return bb[3]


def _draw_brush_underline(img: Image.Image, x0: int, y: int,
                          length: int, color: tuple[int, int, int]) -> None:
    """Hand-drawn-looking underline. Implemented as a slightly arched,
    tapered stroke painted with multiple overlapping ovals."""
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    steps = max(40, length // 6)
    for i in range(steps):
        t = i / (steps - 1)
        # Slight upward arch in the middle: parabola
        arch = -10 * (4 * t * (1 - t))
        cx = x0 + int(t * length)
        cy = y + int(arch)
        # Thickness tapers at both ends.
        edge_t = min(t, 1 - t) * 2  # 0..1..0
        thickness = 4 + int(8 * edge_t)
        alpha = 230 if 0.05 < t < 0.95 else int(230 * edge_t * 4)
        rgba = (*color, max(0, min(255, alpha)))
        d.ellipse((cx - thickness // 2, cy - thickness // 2,
                   cx + thickness // 2, cy + thickness // 2), fill=rgba)
    img.paste(overlay, (0, 0), overlay)


def _composite_cutout(rgba: Image.Image, target_w: int, target_h: int,
                      bg: tuple[int, int, int]) -> Image.Image:
    """Place an rembg cutout (RGBA, transparent background) onto a
    coloured page. Crops to the subject's bounding box, scales to fill
    the target frame, anchors the subject to the bottom-center.
    """
    # rembg leaves stray semi-transparent pixels around the subject;
    # `getbbox()` over the raw alpha picks them up and gives a loose
    # bbox that shrinks the actual subject. Threshold the alpha at
    # ~50% before measuring so the bbox hugs the solid silhouette.
    alpha = rgba.split()[3]
    solid = alpha.point(lambda v: 255 if v > 128 else 0)
    bbox = solid.getbbox()
    if bbox:
        rgba = rgba.crop(bbox)
    sw, sh = rgba.size
    if sw == 0 or sh == 0:
        return Image.new("RGB", (target_w, target_h), bg)
    scale = min(target_w / sw, target_h / sh)
    new_w, new_h = max(1, int(sw * scale)), max(1, int(sh * scale))
    rgba = rgba.resize((new_w, new_h), Image.LANCZOS)
    out = Image.new("RGB", (target_w, target_h), bg)
    px = (target_w - new_w) // 2
    py = target_h - new_h  # bottom-anchored — subject 'sits' on the page
    out.paste(rgba, (px, py), rgba)
    return out


def _soft_fade_photo(photo: Image.Image, target_w: int, target_h: int,
                     bg: tuple[int, int, int]) -> Image.Image:
    """Compose the article photo with a soft radial fade into `bg`.

    Returns an RGB image sized target_w × target_h. The mask is opaque
    in the bottom-right ~60% and fades smoothly toward transparent at
    the top-left corner, so the photo reads as 'rising out of' the
    page rather than pasted onto it.
    """
    photo = smart_cover(photo, target_w, target_h, prefer_top=False)
    if photo.mode != "RGB":
        photo = photo.convert("RGB")

    # Precompute a per-pixel radial mask from the bottom-right corner.
    # Center the falloff slightly inside the image so the dense subject
    # area stays opaque. Using putdata is much faster than per-pixel
    # ImageDraw calls.
    cx = target_w * 0.65
    cy = target_h * 0.60
    # Solid radius vs fade radius — pixels inside r_solid are fully
    # opaque, pixels past r_fade are 0. In between, linear ramp.
    diag = math.hypot(target_w, target_h)
    r_solid = diag * 0.28
    r_fade = diag * 0.78

    data = []
    for y in range(target_h):
        for x in range(target_w):
            d = math.hypot(x - cx, y - cy)
            if d <= r_solid:
                v = 255
            elif d >= r_fade:
                v = 0
            else:
                t = (d - r_solid) / (r_fade - r_solid)
                # Smoothstep for prettier falloff.
                t = t * t * (3 - 2 * t)
                v = int(255 * (1 - t))
            data.append(v)
    mask = Image.new("L", (target_w, target_h))
    mask.putdata(data)
    # Tiny blur smooths the smoothstep further.
    mask = mask.filter(ImageFilter.GaussianBlur(radius=6))

    bg_layer = Image.new("RGB", (target_w, target_h), bg)
    return Image.composite(photo, bg_layer, mask)


def _wrap_headline(text: str, max_w: int) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    """Pick the biggest font that fits the title in ≤4 lines.

    fit_font with a tight `min_size` can return a result that still
    overflows max_lines for long titles — we want to keep shrinking
    instead. Drop the floor further (down to 44px) and clamp the
    returned lines so very long titles never spill into the photo.
    """
    for max_lines in (3, 4):
        font, lines = fit_font(
            HEADLINE_FONT, text.upper(), max_w,
            max_size=132, min_size=44, max_lines=max_lines, step=4,
        )
        if len(lines) <= max_lines:
            return font, lines
    # Still overflowing at 44px — keep the result but hard-clip to 4
    # lines so the slide layout stays predictable.
    return font, lines[:4]


def _pick_accent_line_index(lines: list[str]) -> int:
    """Which line gets the accent colour. Mid-line works best visually
    for 3- and 4-line headlines (matches the references)."""
    n = len(lines)
    if n <= 1:
        return 0
    if n == 2:
        return 1
    return 1  # for 3 or 4 lines: second line


def _draw_slide(article: Article, photo_path: str | None,
                topic: TopicConfig,
                slide_num: int, total: int) -> Image.Image:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    margin_x = 80
    inner_w = W - margin_x * 2

    # 1. Brand chip top-left
    chip_y = 70
    _draw_brand_chip(d, topic, margin_x, chip_y)

    # 2. Headline — biggest type, 3-4 lines
    headline_text = clean_headline(article.title)
    font, lines = _wrap_headline(headline_text, inner_w)
    line_height = int(font.size * 1.06)
    accent = _accent_color(topic)
    accent_line = _pick_accent_line_index(lines)

    headline_top = chip_y + 70
    for i, line in enumerate(lines):
        color = accent if i == accent_line else INK
        d.text((margin_x, headline_top + i * line_height),
               line, font=font, fill=color)
    headline_bottom = headline_top + len(lines) * line_height

    # 3. Subtitle: first sentence of description, or fallback to a softened
    # version of the headline if no description.
    subtitle_raw = (article.description or "").strip()
    if not subtitle_raw:
        subtitle_raw = ""
    # First sentence only.
    sub_end = -1
    for stop in (". ", "! ", "? "):
        i = subtitle_raw.find(stop)
        if i > 30 and (sub_end == -1 or i < sub_end):
            sub_end = i + 1
    if sub_end > 0:
        subtitle_raw = subtitle_raw[:sub_end]
    # Clip overly long subtitles to two lines worth.
    if len(subtitle_raw) > 180:
        subtitle_raw = subtitle_raw[:177].rsplit(" ", 1)[0] + "…"

    sub_y = headline_bottom + 38
    if subtitle_raw:
        sub_font, sub_lines = fit_font(
            SUBTITLE_FONT, subtitle_raw, inner_w,
            max_size=34, min_size=24, max_lines=2, step=2,
        )
        sub_line_height = int(sub_font.size * 1.32)
        for i, line in enumerate(sub_lines):
            d.text((margin_x, sub_y + i * sub_line_height),
                   line, font=sub_font, fill=INK_MUTED)
        # Brush stroke UNDER the last subtitle line. Use the actual
        # rendered bbox to be safe — `font.size` is the design size
        # and gives a stroke that lands on the glyphs themselves.
        last_y = sub_y + (len(sub_lines) - 1) * sub_line_height
        last_bb = d.textbbox((margin_x, last_y), sub_lines[-1], font=sub_font)
        last_w = last_bb[2] - last_bb[0]
        stroke_y = last_bb[3] + 16
        stroke_len = min(int(last_w * 0.55), 320)
        _draw_brush_underline(img, margin_x, stroke_y, stroke_len, accent)

    # 4. Photo with background removed, composited bottom-center.
    # Cutouts are larger than the old soft-faded photos because they
    # carry no background — the subject is the whole frame.
    if photo_path:
        try:
            cache_dir = Path(photo_path).parent.parent / "_cutouts"
            cut_path = bg_remove.cutout(photo_path, cache_dir)
            with Image.open(cut_path) as raw:
                photo = raw.copy()
            photo_w, photo_h = 720, 660
            if photo.mode == "RGBA":
                photo_img = _composite_cutout(photo, photo_w, photo_h, BG)
            else:
                # rembg failed — fall back to the soft-fade behaviour
                photo_img = _soft_fade_photo(photo, photo_w, photo_h, BG)
            px = (W - photo_w) // 2 + 60  # center, then nudge right
            py = H - photo_h - 100
            img.paste(photo_img, (px, py))
        except Exception as e:
            log.warning("photo paste failed (%s): %s", photo_path, e)

    # 5. Page counter bottom-right
    counter_font = ImageFont.truetype(COUNTER_FONT, 28)
    counter = f"{slide_num:02d} / {total:02d}"
    cb = d.textbbox((0, 0), counter, font=counter_font)
    cw = cb[2] - cb[0]
    d.text((W - margin_x - cw, H - 60),
           counter, font=counter_font, fill=INK_MUTED)

    # 6. Source attribution bottom-left, tiny
    if article.source:
        src_font = ImageFont.truetype(SUBTITLE_FONT, 18)
        d.text((margin_x, H - 56),
               f"VIA {article.source.upper()}", font=src_font, fill=INK_MUTED)

    return img


def _draw_cta(topic: TopicConfig, slide_num: int, total: int) -> Image.Image:
    """Closing slide: huge headline, no photo. Same brand chip + counter."""
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    margin_x = 80
    inner_w = W - margin_x * 2

    _draw_brand_chip(d, topic, margin_x, 70)

    cta_text = (topic.cta.headline or "FOLLOW FOR MORE").replace("\n", " ").strip()
    font, lines = _wrap_headline(cta_text, inner_w)
    line_height = int(font.size * 1.06)
    accent = _accent_color(topic)
    accent_line = _pick_accent_line_index(lines)

    block_h = len(lines) * line_height
    headline_top = (H - block_h) // 2 - 60
    for i, line in enumerate(lines):
        color = accent if i == accent_line else INK
        d.text((margin_x, headline_top + i * line_height),
               line, font=font, fill=color)

    if topic.cta.subtext:
        sub_font, sub_lines = fit_font(
            SUBTITLE_FONT, topic.cta.subtext, inner_w,
            max_size=32, min_size=22, max_lines=2, step=2,
        )
        sub_y = headline_top + block_h + 32
        for i, line in enumerate(sub_lines):
            d.text((margin_x, sub_y + i * int(sub_font.size * 1.3)),
                   line, font=sub_font, fill=INK_MUTED)

    counter_font = ImageFont.truetype(COUNTER_FONT, 28)
    counter = f"{slide_num:02d} / {total:02d}"
    cb = d.textbbox((0, 0), counter, font=counter_font)
    cw = cb[2] - cb[0]
    d.text((W - margin_x - cw, H - 60),
           counter, font=counter_font, fill=INK_MUTED)
    return img


# ── public render ───────────────────────────────────────────────────────


def render(topic: TopicConfig, articles: list[Article],
           output_dir: Path) -> list[str]:
    if not articles:
        return []
    output_dir.mkdir(parents=True, exist_ok=True)
    img_dir = output_dir / "_images"

    photos = download_images_parallel(
        [a.image_url or None for a in articles], img_dir,
    )

    total = len(articles) + 1  # +1 CTA
    paths: list[str] = []
    for i, (a, p) in enumerate(zip(articles, photos)):
        slide_num = i + 1
        img = _draw_slide(a, p, topic, slide_num, total)
        out = output_dir / f"slide_{slide_num}.png"
        img.save(out, "PNG", quality=92)
        paths.append(str(out))
        log.info("slide %d/%d · %s", slide_num, total, a.source)

    cta = _draw_cta(topic, total, total)
    out = output_dir / f"slide_{total}.png"
    cta.save(out, "PNG", quality=92)
    paths.append(str(out))
    log.info("slide %d/%d · cta", total, total)

    return paths


editorial_white = Design(
    slug="editorial_white",
    name="Editorial White",
    description=(
        "Threads-style editorial layout: white background, huge sans-serif "
        "headline broken across 3-4 lines with one line in the topic's "
        "accent colour, a muted-gray subtitle under a hand-drawn brush "
        "underline, and the article photo composited bottom-right with "
        "a soft radial fade into the page. No frames, no brand chrome."
    ),
    render=render,
)

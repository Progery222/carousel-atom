"""Polaroid Stack design — intimate, hand-album-style sports carousel.

Visual reference: the @gloriwht-style "кайфуйте со мной" Threads posts —
warm pastel palette, soft personal feel, like flipping through a friend's
photo album. We already have `seamless` for the bleed/continuous-image
trick from those references; this design covers the OTHER half — the
warm intimate aesthetic that those carousels share independent of the
seamless mechanic.

  ┌────────────────────────────────┐
  │     ╲                          │
  │      ╲ ← polaroid card, ±3°    │
  │       ╲    tilt per slide       │
  │   ┌───────┐                    │
  │   │       │                    │
  │   │ photo │  ← smart-cropped   │
  │   │       │                    │
  │   │       │                    │
  │   └───────┘                    │
  │   ' caption in handwritten '   │
  │   ' MarkerFelt below photo '   │
  │                                │
  │  cream → peach pastel bg       │
  │                          01    │
  └────────────────────────────────┘

The vibe is the opposite of `highlight_reel`: where that screams for
attention with outlined yellow + red ribbons, this whispers.
"""
from __future__ import annotations

import hashlib
import os
import random
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from core.http import download_images_parallel
from core.image import smart_cover
from core.log import get_logger
from core.parsers.base import Article
from core.quality import emoji_font_path, news_emoji
from core.text import clean_headline
from core.topic_loader import TopicConfig
from core.typography import balanced_wrap

from designs.base import Design

log = get_logger("design.polaroid")

CORE_FONTS = Path(__file__).resolve().parent.parent / "core" / "assets" / "fonts"
FALLBACK_HEADLINE = str(CORE_FONTS / "Anton-Regular.ttf")
FALLBACK_BODY = str(CORE_FONTS / "BebasNeue-Regular.ttf")

# macOS system fonts that give the polaroid feel.
HANDWRITTEN_CANDIDATES = (
    "/System/Library/Fonts/MarkerFelt.ttc",        # marker-style — best for caption
    "/System/Library/Fonts/HelveticaNeue.ttc",     # fallback (will use italic face)
)
SERIF_ITALIC_CANDIDATES = (
    "/System/Library/Fonts/NewYorkItalic.ttf",     # serif italic for page numbers
    "/System/Library/Fonts/SFCompactItalic.ttf",
    "/System/Library/Fonts/HelveticaNeue.ttc",
)

W, H = 1080, 1350

# Warm cream backgrounds — same across topics for cohesive "album" feel.
# Topic accent leaks in only as a small detail (the corner badge).
BG_TOP = (250, 244, 232)     # cream
BG_BOTTOM = (245, 224, 208)  # soft peach
INK_BODY = (60, 40, 30)       # warm dark brown for body text
INK_MUTED = (140, 110, 90)    # softer brown for secondary
WHITE = (255, 255, 255)
SHADOW = (0, 0, 0)


def _font(paths: tuple[str, ...], size: int) -> ImageFont.FreeTypeFont:
    """First candidate that loads at the given size, else PIL default."""
    for p in paths:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except OSError:
                continue
    return ImageFont.load_default()


# ── background ────────────────────────────────────────────────────────────


def _pastel_background(W_: int, H_: int) -> Image.Image:
    """Vertical cream-to-peach gradient. The same background paints every
    slide, so the carousel reads as one warm physical album rather than
    independent posters."""
    img = Image.new("RGB", (W_, H_), BG_TOP)
    grad = Image.new("RGB", (1, H_), BG_TOP)
    for y in range(H_):
        t = y / max(1, H_ - 1)
        # Quadratic ease — most of the cream stays cream, peach lifts only
        # in the bottom third.
        u = t ** 1.6
        r = int(BG_TOP[0] * (1 - u) + BG_BOTTOM[0] * u)
        g = int(BG_TOP[1] * (1 - u) + BG_BOTTOM[1] * u)
        b = int(BG_TOP[2] * (1 - u) + BG_BOTTOM[2] * u)
        grad.putpixel((0, y), (r, g, b))
    return grad.resize((W_, H_))


# ── polaroid card ─────────────────────────────────────────────────────────


def _build_polaroid(article: Article, photo_path: str | None,
                    rotation_deg: float) -> Image.Image:
    """Build a polaroid card with the photo inside, the caption hand-written
    on the bottom margin, then rotate the whole card by `rotation_deg`.

    Returns an RGBA image with transparent background outside the card
    (so the rotation reveals the underlying pastel)."""
    # Card geometry — classic polaroid 1:1.18 aspect with thick bottom margin.
    card_w, card_h = 720, 880
    photo_w, photo_h = 660, 660
    photo_x = (card_w - photo_w) // 2
    photo_y = 30                          # equal top + sides
    caption_zone_top = photo_y + photo_h + 18

    # White card base
    card = Image.new("RGBA", (card_w, card_h), (0, 0, 0, 0))
    cd = ImageDraw.Draw(card)
    # Subtle rounded rectangle so the corners don't look like a poster
    cd.rounded_rectangle([0, 0, card_w, card_h], radius=6,
                         fill=(252, 250, 246, 255))

    # Photo region
    if photo_path and os.path.exists(photo_path):
        try:
            photo = Image.open(photo_path).convert("RGB")
            photo = smart_cover(photo, photo_w, photo_h, prefer_top=True)
            card.paste(photo, (photo_x, photo_y))
        except Exception as e:
            log.warning("polaroid photo failed: %s", e)
            cd.rectangle(
                [photo_x, photo_y, photo_x + photo_w, photo_y + photo_h],
                fill=(220, 210, 200, 255),
            )
    else:
        cd.rectangle(
            [photo_x, photo_y, photo_x + photo_w, photo_y + photo_h],
            fill=(220, 210, 200, 255),
        )

    # Caption: handwritten marker, sentence-case, trimmed to fit polaroid bottom
    caption = _polaroid_caption(article)
    cap_font = _font(HANDWRITTEN_CANDIDATES, 38)
    # Wrap to up to 2 lines within the card width minus margin
    margin = 36
    cap_lines = balanced_wrap(caption, cap_font,
                              max_w=card_w - margin * 2, max_lines=2)
    cap_line_h = cap_font.getbbox("Hg")[3] + 6
    block_h = cap_line_h * len(cap_lines)
    cap_y = caption_zone_top + ((card_h - caption_zone_top - 20) - block_h) // 2

    for ln in cap_lines:
        bb = cap_font.getbbox(ln)
        tw = bb[2] - bb[0]
        x = (card_w - tw) // 2 - bb[0]
        cd.text((x, cap_y), ln, font=cap_font, fill=INK_BODY)
        cap_y += cap_line_h

    # Rotate the whole card around its center, expand canvas so corners fit
    rotated = card.rotate(rotation_deg, resample=Image.BICUBIC, expand=True)
    return rotated


def _polaroid_caption(article: Article) -> str:
    """Headline trimmed and softened — polaroid captions are casual,
    not all-caps. Drop trailing punctuation, lower-case all but proper
    nouns / acronyms."""
    text = clean_headline(article.title).strip()
    # Cap length so it always wraps to ≤2 lines at 38pt
    if len(text) > 80:
        # Cut at a word boundary near 70 chars, append ellipsis
        cut = text.rfind(" ", 0, 70)
        if cut == -1:
            cut = 70
        text = text[:cut].rstrip(",.;:") + "…"
    return text


def _polaroid_drop_shadow(card: Image.Image) -> Image.Image:
    """Soft drop shadow under the rotated polaroid. Returns an RGBA
    image larger than `card` with shadow padded around it; caller pastes
    this onto the background at the correct offset to place the card
    inside."""
    pad = 40
    sw, sh = card.width + pad * 2, card.height + pad * 2
    shadow = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
    # Use the card's alpha as the shadow mask, soften with blur
    alpha = card.split()[-1]
    shadow_mask = Image.new("L", (sw, sh), 0)
    shadow_mask.paste(alpha, (pad, pad + 14))     # offset down for natural drop
    shadow_mask = shadow_mask.filter(ImageFilter.GaussianBlur(radius=18))
    # Fill the shadow with semi-transparent warm dark
    fill = Image.new("RGBA", (sw, sh), (45, 30, 20, 130))
    shadow.paste(fill, (0, 0), shadow_mask)
    # Composite the card over the shadow
    shadow.alpha_composite(card, (pad, pad))
    return shadow


# ── per-slide rendering ───────────────────────────────────────────────────


def _seeded_rotation(article: Article, slide_num: int) -> float:
    """Stable ±2-4° tilt, seeded by article URL + slide index so the
    same article always tilts the same way."""
    seed_src = f"{article.url}:{slide_num}".encode("utf-8")
    seed = int(hashlib.sha1(seed_src).hexdigest()[:8], 16)
    r = random.Random(seed)
    # Alternate sign by slide index so adjacent slides lean opposite ways,
    # giving the album that "tossed loosely on a desk" feel.
    sign = -1 if slide_num % 2 == 0 else 1
    return sign * r.uniform(2.0, 4.5)


def _draw_corner_badge(img: Image.Image, topic: TopicConfig) -> None:
    """Subtle topic emblem in the top-left of the slide — like a museum
    label or stamp on a photo album page. Tiny so it doesn't fight the
    polaroid for attention."""
    d = ImageDraw.Draw(img, "RGBA")
    accent = topic.brand.accent or (200, 80, 60)
    diameter = 56
    x, y = 56, 56
    d.ellipse([x, y, x + diameter, y + diameter], fill=accent + (255,))
    d.ellipse([x + 3, y + 3, x + diameter - 3, y + diameter - 3],
              outline=(255, 255, 255, 220), width=2)
    label = (topic.display_name or topic.slug or "").strip().upper()
    label = label[:1]
    f = _font((FALLBACK_HEADLINE,), int(diameter * 0.55))
    bb = f.getbbox(label)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    d.text((x + diameter // 2 - tw // 2 - bb[0],
            y + diameter // 2 - th // 2 - bb[1] - 4),
           label, font=f, fill=WHITE)

    # Tiny topic name to the right of the badge, in serif italic
    name_font = _font(SERIF_ITALIC_CANDIDATES, 22)
    name = (topic.display_name or topic.slug).strip()
    d.text((x + diameter + 12, y + diameter // 2 - 13),
           name, font=name_font, fill=INK_MUTED)


def _draw_sticker_emoji(canvas: Image.Image, article: Article,
                        card_box: tuple[int, int, int, int]) -> None:
    """Small sentiment emoji "sticker" placed near the top-right corner
    of the polaroid card, with a slight rotation. Reuses the news_emoji
    classifier from quality.py so the sticker matches the article mood."""
    emoji_path = emoji_font_path()
    if emoji_path is None:
        return
    glyph = news_emoji(article)

    # Render emoji at native 160px, downscale to ~72
    native = 160
    target = 72
    buf = Image.new("RGBA", (native, native), (0, 0, 0, 0))
    try:
        ef = ImageFont.truetype(emoji_path, native)
        ImageDraw.Draw(buf).text((0, 0), glyph, font=ef, embedded_color=True)
    except Exception as e:
        log.warning("polaroid emoji failed: %s", e)
        return
    sticker = buf.resize((target, target), Image.LANCZOS)
    # Slight tilt opposite to the card's rotation looks playful
    sticker = sticker.rotate(-12, resample=Image.BICUBIC, expand=True)

    # Anchor to the top-right of the card box
    cx0, cy0, cx1, cy1 = card_box
    x = cx1 - sticker.width // 2 - 30
    y = cy0 - sticker.height // 2 + 30

    base = canvas.convert("RGBA")
    base.alpha_composite(sticker, (x, y))
    canvas.paste(base.convert("RGB"))


def _draw_page_number(img: Image.Image, slide_num: int, total: int) -> None:
    """Page number in the bottom-right corner — serif italic, like
    sketchbook foliation."""
    d = ImageDraw.Draw(img)
    f = _font(SERIF_ITALIC_CANDIDATES, 36)
    txt = f"— {slide_num:02d} / {total:02d} —"
    bb = f.getbbox(txt)
    tw = bb[2] - bb[0]
    th = bb[3] - bb[1]
    x = W - 56 - tw
    y = H - 56 - th - 8
    d.text((x, y), txt, font=f, fill=INK_MUTED)


# ── full slide composition ───────────────────────────────────────────────


def _slide(article: Article, photo_path: str | None, slide_num: int,
           total: int, topic: TopicConfig, output_dir: Path) -> str:
    canvas = _pastel_background(W, H)
    _draw_corner_badge(canvas, topic)

    rotation = _seeded_rotation(article, slide_num)
    card = _build_polaroid(article, photo_path, rotation)
    card_with_shadow = _polaroid_drop_shadow(card)

    # Centre the polaroid + shadow on the canvas, with a slight upward
    # bias so the page number at the bottom has breathing room.
    cx = (W - card_with_shadow.width) // 2
    cy = (H - card_with_shadow.height) // 2 - 30
    base = canvas.convert("RGBA")
    base.alpha_composite(card_with_shadow, (cx, cy))
    canvas = base.convert("RGB")

    # Sentiment emoji sticker — anchored to the card's bounding box
    # (approximated using the post-rotation bbox we just placed).
    card_box = (cx, cy, cx + card_with_shadow.width,
                cy + card_with_shadow.height)
    _draw_sticker_emoji(canvas, article, card_box)

    _draw_page_number(canvas, slide_num, total)

    out = output_dir / f"slide_{slide_num}.png"
    canvas.save(out, "PNG", quality=92)
    return str(out)


def render(topic: TopicConfig, articles: list[Article],
           output_dir: Path) -> list[str]:
    """One polaroid per article — no CTA, mirrors the cadence of
    `tiktok_news` / `highlight_reel`."""
    output_dir.mkdir(parents=True, exist_ok=True)
    img_dir = output_dir / "_images"
    local_imgs = download_images_parallel(
        [a.image_url or None for a in articles], img_dir,
    )

    total = len(articles)
    paths: list[str] = []
    for i, (art, photo) in enumerate(zip(articles, local_imgs), start=1):
        log.info("polaroid %d/%d · %s", i, total, art.source)
        paths.append(_slide(art, photo, i, total, topic, output_dir))
    return paths


polaroid = Design(
    slug="polaroid",
    name="Polaroid Stack",
    description=(
        "Personal photo-album aesthetic: tilted polaroid card on a "
        "warm cream-to-peach pastel background, soft drop shadow, "
        "marker-pen caption below the photo, sentiment emoji sticker, "
        "serif-italic page number. The opposite of Highlight Reel — "
        "quiet, intimate, optimised for slower-scroll watch time."
    ),
    render=render,
)

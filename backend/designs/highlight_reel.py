"""Highlight Reel design — slides styled as YouTube/MrBeast-thumbnail
sports highlights.

The visual language is loud and hyper-recognisable on TikTok:
  - tight crop on the action (face / catch / collision)
  - subtle red vignette to push focus into the centre
  - giant outlined headline diagonally across the lower-third
  - red corner badge with status word ("🔥 HOT", "BREAKING", "WILD",
    "MUST SEE") seeded by article sentiment
  - bottom strip with source + slide counter

The pattern is borrowed from sports YouTube thumbnails which optimise
for thumb-stop-rate above all. We use it for high-energy news where
the photo IS the headline (dunks, goals, knockouts, comeback moments).

Like the original `tiktok_news`, this design is one article per slide,
no CTA — every slide is a real story.
"""
from __future__ import annotations

import hashlib
import os
import random
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from core.http import download_images_parallel
from core.image import punch, smart_cover
from core.log import get_logger
from core.parsers.base import Article
from core.text import clean_headline, punchy
from core.topic_loader import TopicConfig
from core.typography import fit_font

from designs.base import Design

log = get_logger("design.highlight_reel")

CORE_FONTS = Path(__file__).resolve().parent.parent / "core" / "assets" / "fonts"
FALLBACK_HEADLINE = str(CORE_FONTS / "Anton-Regular.ttf")
FALLBACK_BODY = str(CORE_FONTS / "BebasNeue-Regular.ttf")

W, H = 1080, 1350      # newsflash-compatible TikTok-friendly canvas

WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
HOT_RED = (227, 28, 28)
HOT_YELLOW = (255, 215, 0)
SHADOW = (0, 0, 0, 200)


def _font(path: str | None, size: int, fallback: str) -> ImageFont.FreeTypeFont:
    p = path if (path and os.path.exists(path)) else fallback
    try:
        return ImageFont.truetype(p, size)
    except OSError:
        return ImageFont.load_default()


# ── status badge selection ────────────────────────────────────────────────


_BREAKING_RE = re.compile(
    r"\b(breaking|just\s+in|crash|dies|injury|hospital|fired|sacked)\b",
    re.IGNORECASE,
)
_WILD_RE = re.compile(
    r"\b(stunning|shocking|wild|insane|brutal|epic|incredible|jaw[-\s]?dropping|"
    r"bombshell|drama|chaos|disaster)\b",
    re.IGNORECASE,
)
_WIN_RE = re.compile(
    r"\b(wins?|won|champion|takes|claims?|smashes?|dominant|record|"
    r"triumph|gold|victory|crowned)\b",
    re.IGNORECASE,
)
_QUOTE_RE = re.compile(r'(?:["“”]|\b(?:says|claims|told|admits)\b)', re.IGNORECASE)


def _pick_badge(article: Article) -> str:
    """Choose the corner badge label based on the article's tone.
    Same vibe as the sentiment-emoji classifier, but emits a single
    punchy English word that fits a YouTube-thumbnail badge."""
    blob = f"{article.title} {article.description or ''}"
    if _BREAKING_RE.search(blob):
        return "BREAKING"
    if _WILD_RE.search(blob):
        return "WILD"
    if _WIN_RE.search(blob):
        return "🏆 HUGE"
    if _QUOTE_RE.search(blob):
        return "HOT TAKE"
    # Pseudo-random fallback so non-classified slides still feel curated
    # rather than all carrying the same default badge.
    seed = int(hashlib.sha1(article.url.encode("utf-8")).hexdigest()[:8], 16)
    options = ["🔥 HOT", "MUST SEE", "TODAY", "GO VIRAL"]
    return options[seed % len(options)]


# ── photo treatment ──────────────────────────────────────────────────────


def _hero_with_vignette(photo_path: str | None) -> Image.Image:
    """Smart-cover the hero photo, punch contrast, then paint a radial
    red vignette so the eye snaps to the centre and the corners read
    as 'thumbnail-graphic' rather than 'cropped photo'."""
    if not photo_path or not os.path.exists(photo_path):
        return Image.new("RGB", (W, H), (40, 0, 0))
    try:
        img = Image.open(photo_path).convert("RGB")
        img = smart_cover(img, W, H, prefer_top=True)
        img = punch(img, contrast=1.28, saturation=1.30)
    except Exception as e:
        log.warning("hero failed: %s", e)
        return Image.new("RGB", (W, H), (40, 0, 0))

    # Radial vignette: build a smaller alpha gradient and upscale to W×H.
    # Smaller intermediate buffer keeps the blur cheap.
    gw, gh = 360, 450
    grad = Image.new("L", (gw, gh), 0)
    gd = ImageDraw.Draw(grad)
    cx, cy = gw // 2, gh // 2
    max_r = (cx ** 2 + cy ** 2) ** 0.5
    # Paint concentric ellipses from outer (more opaque) to inner (transparent)
    for r in range(int(max_r), 0, -8):
        # Outer ring strongest, decays cubically toward centre
        t = r / max_r
        alpha = int((t ** 1.6) * 220)
        gd.ellipse([cx - r, cy - r, cx + r, cy + r], fill=alpha)
    grad = grad.resize((W, H), Image.LANCZOS)
    grad = grad.filter(ImageFilter.GaussianBlur(radius=40))

    # Tint the vignette with a hint of red (matches HOT_RED brand cue)
    overlay = Image.new("RGBA", (W, H), (40, 0, 0, 0))
    overlay.putalpha(grad)
    base = img.convert("RGBA")
    base.alpha_composite(overlay)
    return base.convert("RGB")


# ── corner badge ─────────────────────────────────────────────────────────


def _draw_corner_badge(img: Image.Image, label: str) -> None:
    """Tilted red ribbon-style badge in the top-right corner. Black
    drop shadow, white text, ~14° tilt to look "stuck on" the slide
    rather than aligned to the grid."""
    badge_font = _font(FALLBACK_HEADLINE, 56, FALLBACK_HEADLINE)
    bb = badge_font.getbbox(label)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    pad_x, pad_y = 32, 14
    bw, bh = tw + pad_x * 2, th + pad_y * 2

    # Build the badge on a transparent buffer so we can rotate it whole.
    pad_for_rotation = 24
    badge = Image.new("RGBA",
                      (bw + pad_for_rotation * 2, bh + pad_for_rotation * 2),
                      (0, 0, 0, 0))
    bd = ImageDraw.Draw(badge)
    bd.rectangle(
        [pad_for_rotation, pad_for_rotation,
         pad_for_rotation + bw, pad_for_rotation + bh],
        fill=HOT_RED + (255,),
    )
    # Tiny white inner outline
    bd.rectangle(
        [pad_for_rotation + 4, pad_for_rotation + 4,
         pad_for_rotation + bw - 4, pad_for_rotation + bh - 4],
        outline=(255, 255, 255, 220), width=2,
    )
    bd.text(
        (pad_for_rotation + pad_x - bb[0],
         pad_for_rotation + pad_y - bb[1] - 4),
        label, font=badge_font, fill=WHITE,
    )

    badge = badge.rotate(14, resample=Image.BICUBIC, expand=True)

    # Anchor to top-right with a margin so the rotated corners don't
    # clip outside the slide.
    margin = 24
    x = W - badge.width + 30
    y = -20 + margin

    base = img.convert("RGBA")
    base.alpha_composite(badge, (x, y))
    img.paste(base.convert("RGB"))


# ── headline (outlined + drop shadow) ────────────────────────────────────


def _draw_outlined_headline(img: Image.Image, title: str,
                            topic: TopicConfig) -> None:
    """Big yellow uppercase headline with thick black outline + drop
    shadow. Sits in the lower-third of the slide. Outlined typography
    is the single most reliable thumbnail trick — it stays readable
    on absolutely any background."""
    headline_path = topic.brand.font_headline or FALLBACK_HEADLINE
    text = punchy(clean_headline(title)).upper()

    # The bottom third is where headlines live. Leave room above for
    # the photo focus and below for the source-counter strip.
    safe_w = W - 80
    block_top = int(H * 0.55)
    block_bottom = H - 130

    font, lines = fit_font(
        headline_path, text, max_w=safe_w,
        max_size=120, min_size=64, max_lines=3,
    )
    line_h = font.getbbox("Hg")[3] + 12
    block_h = line_h * len(lines)
    # Bottom-anchored within the bottom-third zone
    text_y = block_bottom - block_h
    if text_y < block_top:
        text_y = block_top

    d = ImageDraw.Draw(img)

    for line in lines:
        bb = font.getbbox(line)
        tw = bb[2] - bb[0]
        x = (W - tw) // 2 - bb[0]
        # Black outline: stamp the text in 8 directions slightly offset.
        # We use a 4-px stroke approximated by 8 jittered text() calls
        # because PIL's stroke_width is OS-version-dependent.
        for dx, dy in ((-4, 0), (4, 0), (0, -4), (0, 4),
                       (-3, -3), (3, -3), (-3, 3), (3, 3)):
            d.text((x + dx, text_y + dy), line, font=font, fill=BLACK)
        # Soft drop-shadow underneath (bigger offset, semi-transparent)
        # Approximated with a darker stroke since we render to RGB.
        d.text((x + 6, text_y + 10), line, font=font, fill=(20, 20, 20))
        # Fill in HOT_YELLOW
        d.text((x, text_y), line, font=font, fill=HOT_YELLOW)
        text_y += line_h


# ── footer (source + counter) ────────────────────────────────────────────


def _draw_footer(img: Image.Image, source: str,
                 slide_num: int, total: int) -> None:
    """Dark strip with `VIA <SOURCE>` left + `N / TOTAL` right. Drops
    nicely below the headline."""
    d = ImageDraw.Draw(img, "RGBA")
    strip_h = 70
    strip_y = H - strip_h - 30
    d.rectangle([0, strip_y, W, H], fill=(0, 0, 0, 180))

    font = _font(FALLBACK_BODY, 34, FALLBACK_BODY)
    src = f"VIA {source.upper()}"
    sb = font.getbbox(src)
    d.text((40, strip_y + (strip_h - (sb[3] - sb[1])) // 2 - sb[1]),
           src, font=font, fill=(255, 255, 255, 220))

    counter = f"{slide_num:02d} / {total:02d}"
    cb = font.getbbox(counter)
    cw = cb[2] - cb[0]
    d.text((W - 40 - cw,
            strip_y + (strip_h - (cb[3] - cb[1])) // 2 - cb[1]),
           counter, font=font, fill=HOT_YELLOW + (255,))


# ── public render ────────────────────────────────────────────────────────


def _slide(article: Article, photo_path: str | None,
           slide_num: int, total: int, topic: TopicConfig,
           output_dir: Path) -> str:
    img = _hero_with_vignette(photo_path)
    _draw_outlined_headline(img, article.title, topic)
    _draw_corner_badge(img, _pick_badge(article))
    _draw_footer(img, article.source, slide_num, total)

    out = output_dir / f"slide_{slide_num}.png"
    img.save(out, "PNG", quality=92)
    return str(out)


def render(topic: TopicConfig, articles: list[Article],
           output_dir: Path) -> list[str]:
    """One slide per article — same cadence as `tiktok_news`. No CTA."""
    output_dir.mkdir(parents=True, exist_ok=True)
    img_dir = output_dir / "_images"
    local_imgs = download_images_parallel(
        [a.image_url or None for a in articles], img_dir,
    )

    total = len(articles)
    paths: list[str] = []
    for i, (art, photo) in enumerate(zip(articles, local_imgs), start=1):
        log.info("highlight %d/%d · %s", i, total, art.source)
        paths.append(_slide(art, photo, i, total, topic, output_dir))
    return paths


highlight_reel = Design(
    slug="highlight_reel",
    name="Highlight Reel",
    description=(
        "YouTube-thumbnail-style sports highlights: tight crop with "
        "red vignette pulling focus to the action, giant outlined "
        "yellow headline in the lower third, tilted red corner "
        "badge (BREAKING / WILD / 🏆 HUGE / HOT TAKE). Optimised "
        "for thumb-stop-rate on high-energy moments."
    ),
    render=render,
)

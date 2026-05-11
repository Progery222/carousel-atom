"""Viral roundup design — dark photo backgrounds with heavy overlays,
huge stacked headlines, orange/red accents, big rank numbers per slide.

Generalised from the original NBA roundup. Same input contract as any
Design: (topic, articles, output_dir) -> list[png paths].
"""
from __future__ import annotations

import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from core.copy import hook_copy, cta_copy, story_count_label
from core.http import download_images_parallel
from core.image import darken_band_under_text, smart_cover
from core.log import get_logger
from core.parsers.base import Article
from core.quality import severity_of
from core.topic_loader import TopicConfig
from designs.base import Design

log = get_logger("design.viral_roundup")

CORE_FONTS = Path(__file__).resolve().parent.parent / "core" / "assets" / "fonts"
HEADLINE_FONT = str(CORE_FONTS / "Anton-Regular.ttf")
BODY_FONT = str(CORE_FONTS / "BebasNeue-Regular.ttf")

WHITE = (255, 255, 255)
ORANGE = (255, 107, 26)
RED = (220, 30, 30)
GREY = (180, 180, 180)
BG = (10, 10, 10)


# ── primitives ───────────────────────────────────────────────────────────────

def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


def _text_size(d: ImageDraw.ImageDraw, s: str, f: ImageFont.FreeTypeFont):
    l, t, r, b = d.textbbox((0, 0), s, font=f)
    return r - l, b - t


def _centered(d, y, text, font, color=WHITE, W=1080):
    w, _ = _text_size(d, text, font)
    d.text(((W - w) / 2, y), text, font=font, fill=color)


def _fit_centered(d, y, text, font_path, max_size, color=WHITE, max_w=980, W=1080):
    size = max_size
    while size > 30:
        f = _font(font_path, size)
        w, _ = _text_size(d, text, f)
        if w <= max_w:
            break
        size -= 4
    _centered(d, y, text, f, color=color, W=W)


def _fit_cover(img: Image.Image, w: int, h: int) -> Image.Image:
    """Backwards-compatible wrapper around `smart_cover` so existing callers
    inside this module keep working. Falls back to a centre crop if the
    saliency pass blows up for any reason."""
    try:
        return smart_cover(img, w, h, prefer_top=True)
    except Exception:
        iw, ih = img.size
        src_ratio, dst_ratio = iw / ih, w / h
        if src_ratio > dst_ratio:
            new_w = int(ih * dst_ratio)
            x0 = (iw - new_w) // 2
            img = img.crop((x0, 0, x0 + new_w, ih))
        else:
            new_h = int(iw / dst_ratio)
            y0 = (ih - new_h) // 2
            img = img.crop((0, y0, iw, y0 + new_h))
        return img.resize((w, h), Image.LANCZOS)


def _darken(img: Image.Image, amount: float) -> Image.Image:
    overlay = Image.new("RGBA", img.size, (0, 0, 0, int(255 * amount)))
    img = img.convert("RGBA")
    img.alpha_composite(overlay)
    return img.convert("RGB")


# Image downloads are delegated to `core.http`; kept as a thin shim for
# backwards compatibility with anything that imported `_download_image`.
def _download_image(url: str, save_dir: Path) -> str | None:
    from core.http import _download_one
    return _download_one(url, save_dir)


def _photo_bg(image_path: str | None, W: int, H: int, dark: float = 0.62) -> Image.Image:
    if image_path and os.path.exists(image_path):
        try:
            img = Image.open(image_path).convert("RGB")
            img = _fit_cover(img, W, H)
            return _darken(img, dark) if dark > 0 else img
        except Exception:
            pass
    return Image.new("RGB", (W, H), BG)


def _accent_bar(d, W: int, H: int, color=ORANGE):
    d.rectangle([(0, H - 12), (W, H)], fill=color)


def _badge(d, label: str, y: int, color, W: int, font_size: int = 70):
    f = _font(HEADLINE_FONT, font_size)
    pad_x, pad_y = 36, 18
    tw, th = _text_size(d, label, f)
    box_w, box_h = tw + pad_x * 2, th + pad_y * 2
    x = (W - box_w) / 2
    d.rectangle([(x, y), (x + box_w, y + box_h)], fill=color)
    d.text((x + pad_x, y + pad_y - 8), label, font=f, fill=WHITE)


def _rank_badge(img: Image.Image, num: int, color=ORANGE, x=80, y=120, size=200):
    d = ImageDraw.Draw(img)
    d.text((x, y), f"#{num}", font=_font(HEADLINE_FONT, size), fill=color)


def _wrap_to_width(text: str, font: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    """Greedy word-wrap. Returns lines that each fit within max_w."""
    words = text.split()
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        trial = " ".join(current + [word])
        bb = font.getbbox(trial)
        if (bb[2] - bb[0]) > max_w and current:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))
    return lines


def _draw_slide_counter(img: Image.Image, current: int, total: int) -> None:
    """Big readable "X / Y" counter in the top-right corner with shadow."""
    W, _ = img.size
    text = f"{current + 1} / {total}"
    font = _font(HEADLINE_FONT, 60)
    d = ImageDraw.Draw(img)
    bb = font.getbbox(text)
    tw = bb[2] - bb[0]
    x = W - tw - 70
    y = 70
    d.text((x + 3, y + 3), text, font=font, fill=(0, 0, 0))
    d.text((x, y), text, font=font, fill=WHITE)


def _draw_progress_bar(img: Image.Image, current: int, total: int) -> None:
    """Segmented slide indicator. Active white, others muted, on a faint
    dark shadow strip so it stays readable on photos."""
    W, H = img.size
    bar_y = H - 100
    bar_h = 10
    margin = 70
    gap = 10
    available_w = W - margin * 2
    seg_w = (available_w - gap * (total - 1)) / total
    radius = bar_h // 2

    shadow_pad_x = 18
    shadow_pad_y = 12
    shadow = Image.new(
        "RGBA",
        (available_w + shadow_pad_x * 2, bar_h + shadow_pad_y * 2),
        (0, 0, 0, 0),
    )
    sd = ImageDraw.Draw(shadow)
    sd.rounded_rectangle(
        [0, 0, shadow.width - 1, shadow.height - 1],
        radius=14,
        fill=(0, 0, 0, 130),
    )
    img.paste(shadow, (margin - shadow_pad_x, bar_y - shadow_pad_y), shadow)

    draw = ImageDraw.Draw(img)
    for i in range(total):
        x = margin + i * (seg_w + gap)
        color = WHITE if i == current else (95, 95, 95)
        draw.rounded_rectangle(
            [x, bar_y, x + seg_w, bar_y + bar_h],
            radius=radius,
            fill=color,
        )


# ── headline split ───────────────────────────────────────────────────────────

def _split_headline(title: str, max_lines: int = 3) -> list[str]:
    """Break a long article title into ≤max_lines visually balanced lines.
    Heuristic: split on em dash / colon first, then balance remaining words."""
    title = title.upper().strip()
    for sep in [" — ", " – ", " - ", ": ", " | "]:
        if sep in title:
            parts = [p.strip() for p in title.split(sep) if p.strip()]
            if 1 < len(parts) <= max_lines:
                return parts
    words = title.split()
    if len(words) <= 4:
        return [title]
    target = max(2, min(max_lines, len(words) // 4))
    per = max(1, len(words) // target)
    lines = []
    for i in range(0, len(words), per):
        lines.append(" ".join(words[i:i + per]))
        if len(lines) == target:
            remaining = words[(i + per):]
            if remaining:
                lines[-1] = " ".join(words[i:] )
            break
    return lines[:max_lines]


# ── slide templates ──────────────────────────────────────────────────────────

def _hook_slide(topic: TopicConfig, articles: list[Article], hero_img: str | None,
                output_dir: Path, total: int) -> str:
    W, H = topic.carousel.width, topic.carousel.height
    accent = topic.brand.accent

    # Severity-aware tone: if any article is tragic, drop the goofy
    # "WILL SHOCK YOU" hook and use a neutral tone instead. Otherwise
    # pick a randomised hook from the topic's pool (configured in YAML).
    has_severe = any(severity_of(a) == "severe" for a in articles)
    tone = "severe" if has_severe else "viral"
    h = hook_copy(topic, tone=tone)
    label = story_count_label(topic)
    n = len(articles)

    img = _photo_bg(hero_img, W, H, dark=0.72)
    d = ImageDraw.Draw(img)

    _badge(d, h.badge, y=int(H * 0.10), color=RED, W=W)

    base = int(H * 0.24)
    step = int(H * 0.10)
    _fit_centered(d, base,            h.line1.format(n=n, label=label), HEADLINE_FONT, 180, W=W)
    _fit_centered(d, base + step,     h.line2,                          HEADLINE_FONT, 180, color=accent, W=W)
    _fit_centered(d, base + step * 2, h.line3,                          HEADLINE_FONT, 180, W=W)

    _centered(d, int(H * 0.60), h.sub1, _font(BODY_FONT, 54), W=W)
    _centered(d, int(H * 0.64), h.sub2, _font(BODY_FONT, 54), W=W)

    if h.tease:
        _fit_centered(d, int(H * 0.77), h.tease, HEADLINE_FONT, 90, color=accent, W=W)

    _accent_bar(d, W, H, color=accent)
    _draw_progress_bar(img, 0, total)
    _draw_slide_counter(img, 0, total)
    out = output_dir / "slide_1.png"
    img.save(out, "PNG", quality=95)
    return str(out)


def _news_slide(article: Article, image_path: str | None, rank: int,
                slide_num: int, total: int, topic: TopicConfig,
                output_dir: Path) -> str:
    W, H = topic.carousel.width, topic.carousel.height
    accent = topic.brand.accent
    img = _photo_bg(image_path, W, H, dark=0.62)
    d = ImageDraw.Draw(img)

    _rank_badge(img, rank, color=accent)

    lines = _split_headline(article.title, max_lines=3)
    base_y = int(H * 0.22)
    step = int(H * 0.085)
    sizes = [150, 140, 130]
    # Apply readability scrim across the headline band before drawing.
    darken_band_under_text(
        img,
        (40, base_y - 30, W - 40, base_y + step * len(lines) + 60),
        threshold=95.0,
    )
    for i, line in enumerate(lines):
        size = sizes[min(i, len(sizes) - 1)]
        color = accent if i == len(lines) - 1 and len(lines) > 1 else WHITE
        _fit_centered(d, base_y + i * step, line, HEADLINE_FONT, size, color=color, W=W)

    if article.description:
        desc = article.description.strip()
        if len(desc) > 180:
            desc = desc[:180].rsplit(" ", 1)[0] + "…"
        body_font = _font(BODY_FONT, 50)
        margin = 70
        body_lines = _wrap_to_width(desc, body_font, W - margin * 2)[:3]
        body_y = int(H * 0.56)
        line_h = 70
        for j, line in enumerate(body_lines):
            _centered(d, body_y + j * line_h, line, body_font, W=W)

    _accent_bar(d, W, H, color=accent)
    _draw_progress_bar(img, slide_num - 1, total)
    _draw_slide_counter(img, slide_num - 1, total)
    out = output_dir / f"slide_{slide_num}.png"
    img.save(out, "PNG", quality=95)
    return str(out)


def _cta_slide(topic: TopicConfig, hero_img: str | None, slide_num: int,
               total: int, output_dir: Path, *, tone: str = "viral") -> str:
    W, H = topic.carousel.width, topic.carousel.height
    accent = topic.brand.accent
    cta = cta_copy(topic, tone=tone)

    img = _photo_bg(hero_img, W, H, dark=0.7)
    d = ImageDraw.Draw(img)

    base = int(H * 0.16)
    step = int(H * 0.10)
    _fit_centered(d, base,            cta.q1, HEADLINE_FONT, 160, W=W)
    _fit_centered(d, base + step,     cta.q2, HEADLINE_FONT, 160, W=W)
    _fit_centered(d, base + step * 2, cta.q3, HEADLINE_FONT, 160, color=accent, W=W)

    _centered(d, int(H * 0.52), cta.prompt1, _font(BODY_FONT, 58), W=W)
    _centered(d, int(H * 0.56), cta.prompt2, _font(BODY_FONT, 58), W=W)

    n = topic.carousel.news_per_carousel
    rank_strip = "  »  ".join(str(i) for i in range(1, n + 1))
    _centered(d, int(H * 0.66), rank_strip,
              _font(HEADLINE_FONT, 80), color=accent, W=W)

    _centered(d, int(H * 0.80), "FOLLOW »", _font(HEADLINE_FONT, 80), color=accent, W=W)
    sub = (topic.cta.subtext or f"for daily {topic.display_name}").lower()
    _centered(d, int(H * 0.88), sub, _font(BODY_FONT, 46), color=GREY, W=W)

    _accent_bar(d, W, H, color=accent)
    _draw_progress_bar(img, slide_num - 1, total)
    _draw_slide_counter(img, slide_num - 1, total)
    out = output_dir / f"slide_{slide_num}.png"
    img.save(out, "PNG", quality=95)
    return str(out)


# ── public render ────────────────────────────────────────────────────────────

def render(topic: TopicConfig, articles: list[Article],
           output_dir: Path) -> list[str]:
    """Hook + N news (with rank #1 = last/biggest) + CTA."""
    output_dir.mkdir(parents=True, exist_ok=True)
    img_dir = output_dir / "_images"

    local_imgs = download_images_parallel(
        [a.image_url or None for a in articles], img_dir,
    )

    hero = local_imgs[0] if local_imgs else None
    paths: list[str] = []

    n = len(articles)
    total = n + 2
    log.info("hook 1/%d", total)
    paths.append(_hook_slide(topic, articles, hero, output_dir, total))

    for i, (art, local) in enumerate(zip(articles, local_imgs)):
        rank = n - i
        slide_num = i + 2
        log.info("news %d/%d (rank #%d)", slide_num, total, rank)
        paths.append(_news_slide(art, local, rank, slide_num, total, topic, output_dir))

    has_severe = any(severity_of(a) == "severe" for a in articles)
    log.info("cta %d/%d (tone=%s)", total, total, "severe" if has_severe else "viral")
    paths.append(_cta_slide(topic, hero, total, total, output_dir,
                            tone="severe" if has_severe else "viral"))
    return paths


viral_roundup = Design(
    slug="viral_roundup",
    name="Viral Roundup",
    description=(
        "Dramatic photo backgrounds with heavy overlays, ranked countdown "
        "(#5 → #1), giant orange-and-red headlines. Built for viral hooks "
        "like \"5 stories blowing up right now\"."
    ),
    render=render,
)

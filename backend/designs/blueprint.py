"""Blueprint design — a single-subject technical-drawing poster.

The hero photo is edge-detected into a clean white line drawing and
composed onto a deep cobalt-blue canvas with a subtle engineering grid,
corner brackets, measurement ticks, an arrow with a label pointing at
the subject, and a small inset view in the bottom-left. The headline
sits at the bottom in tall Bebas caps; technical labels (FIG. N,
dimensions, slide counter) use a monospaced font so the whole slide
reads as a real blueprint sheet rather than a photo with a filter.

Inputs / outputs match the rest of the design system: takes a topic +
list of articles + output dir, returns slide PNG paths.
"""
from __future__ import annotations

import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from core.http import download_images_parallel
from core.log import get_logger
from core.parsers.base import Article
from core.text import clean_description, punchy
from core.topic_loader import TopicConfig
from core.typography import balanced_wrap

from designs.base import Design

log = get_logger("design.blueprint")

CORE_FONTS = Path(__file__).resolve().parent.parent / "core" / "assets" / "fonts"
HEADLINE_FONT = str(CORE_FONTS / "BebasNeue-Regular.ttf")
LABEL_FONT_CANDIDATES = (
    "/System/Library/Fonts/SFNSMono.ttf",
    "/System/Library/Fonts/Menlo.ttc",
    "/System/Library/Fonts/Courier.ttc",
)

# Hard-locked TikTok-native canvas — same as tiktok_news.
W, H = 1080, 1920

# Cobalt blueprint palette (RGB).
COBALT      = (8, 32, 78)         # page bg
COBALT_DEEP = (5, 22, 60)         # vignette / overlay
WHITE       = (255, 255, 255)
WHITE_DIM   = (230, 240, 255)
HAIRLINE    = (255, 255, 255, 38)  # ~15% white for grid
HAIRLINE_2  = (255, 255, 255, 64)  # ~25% white for major grid
LINE        = (255, 255, 255, 230) # near-solid white for construction lines

# Photo region (top half-ish) and headline region (bottom).
SAFE_X = 90
PHOTO_TOP = 280
PHOTO_BOTTOM = 1280
HEADLINE_TOP = 1380
HEADLINE_BOTTOM = H - 200


def _label_font(size: int) -> ImageFont.FreeTypeFont:
    for p in LABEL_FONT_CANDIDATES:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _headline_font(size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(HEADLINE_FONT, size)
    except OSError:
        return ImageFont.load_default()


# ── background + grid ──────────────────────────────────────────────────────


def _paint_grid(img: Image.Image) -> None:
    """Engineering grid: 30px minor lines + 120px major lines.

    Both rendered as semi-transparent white onto the cobalt base. The
    composite is done on an RGBA overlay so the cobalt stays saturated
    (alpha-blending darker base via additive paint would shift hue)."""
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    minor, major = 30, 120
    for x in range(0, W, minor):
        d.line([(x, 0), (x, H)], fill=HAIRLINE if x % major else HAIRLINE_2)
    for y in range(0, H, minor):
        d.line([(0, y), (W, y)], fill=HAIRLINE if y % major else HAIRLINE_2)
    base = img.convert("RGBA")
    base.alpha_composite(overlay)
    img.paste(base.convert("RGB"))


# ── photo → white line art ─────────────────────────────────────────────────


def _to_line_art(photo: Image.Image, *, target_w: int, target_h: int) -> Image.Image:
    """Turn a photo into a clean white edge-drawing on a transparent
    background. Uses Pillow's built-in edge filter then thresholds the
    result so faint texture noise drops out and only confident contours
    survive. Returns an RGBA image sized (target_w × target_h)."""
    # Letterbox-fit the photo into target so the subject keeps its
    # proportions — line art looks weird if you stretch.
    src = ImageOps.contain(photo, (target_w, target_h), Image.LANCZOS)

    # Boost contrast first — photos with low contrast (overcast, soft
    # studio lighting) produce mushy edges otherwise.
    g = ImageOps.autocontrast(src.convert("L"), cutoff=3)
    # Very mild blur kills texture/JPEG noise that would otherwise become
    # tangled hairline edges.
    g = g.filter(ImageFilter.GaussianBlur(radius=1.2))

    edges = g.filter(ImageFilter.FIND_EDGES)
    # FIND_EDGES bleeds at the image border (it can't compute neighbours
    # for the outermost row/column) — crop one pixel and pad back to
    # avoid a fake rectangular outline framing the subject.
    edges = ImageOps.crop(edges, border=1)
    edges = ImageOps.expand(edges, border=1, fill=0)

    # Threshold: keep pixels strong enough to be real contours, drop the
    # rest. ~25 is a sweet spot — any lower and you keep speckle, any
    # higher and you lose key contours on darker subjects.
    edges = edges.point(lambda p: 255 if p > 25 else 0)

    # Upscale the binary mask back to canvas resolution if the contained
    # image is smaller than target (preserve crisp lines).
    if edges.size != (target_w, target_h):
        canvas = Image.new("L", (target_w, target_h), 0)
        ox = (target_w - edges.width) // 2
        oy = (target_h - edges.height) // 2
        canvas.paste(edges, (ox, oy))
        edges = canvas

    rgba = Image.new("RGBA", (target_w, target_h), (255, 255, 255, 0))
    rgba.putalpha(edges)
    return rgba


# ── decorations: brackets, ticks, arrow, labels ───────────────────────────


def _draw_corner_brackets(d: ImageDraw.ImageDraw, box: tuple[int, int, int, int],
                          *, length: int = 50, width: int = 4) -> None:
    """Four L-shaped corner brackets framing `box` (x0, y0, x1, y1)."""
    x0, y0, x1, y1 = box
    # top-left
    d.line([(x0, y0), (x0 + length, y0)], fill=LINE, width=width)
    d.line([(x0, y0), (x0, y0 + length)], fill=LINE, width=width)
    # top-right
    d.line([(x1, y0), (x1 - length, y0)], fill=LINE, width=width)
    d.line([(x1, y0), (x1, y0 + length)], fill=LINE, width=width)
    # bottom-left
    d.line([(x0, y1), (x0 + length, y1)], fill=LINE, width=width)
    d.line([(x0, y1), (x0, y1 - length)], fill=LINE, width=width)
    # bottom-right
    d.line([(x1, y1), (x1 - length, y1)], fill=LINE, width=width)
    d.line([(x1, y1), (x1, y1 - length)], fill=LINE, width=width)


def _draw_dimension_ticks(d: ImageDraw.ImageDraw, box: tuple[int, int, int, int],
                          *, dim_label: str | None = None) -> None:
    """Ruler-style measurement ticks under `box` with a centred label."""
    x0, y0, x1, y1 = box
    line_y = y1 + 50
    tick_h = 14
    # main horizontal rule
    d.line([(x0, line_y), (x1, line_y)], fill=LINE, width=2)
    # end caps + arrowheads
    d.line([(x0, line_y - tick_h), (x0, line_y + tick_h)], fill=LINE, width=2)
    d.line([(x1, line_y - tick_h), (x1, line_y + tick_h)], fill=LINE, width=2)
    # tick marks every ~120px
    for x in range(x0, x1 + 1, 120):
        d.line([(x, line_y - 6), (x, line_y + 6)], fill=LINE, width=1)
    # dimension label — small mono text in the centre of the rule
    if dim_label:
        font = _label_font(20)
        bb = font.getbbox(dim_label)
        tw = bb[2] - bb[0]
        # box around the label so the rule visually breaks under it
        pad = 8
        cx = (x0 + x1) // 2
        bx0 = cx - tw // 2 - pad
        bx1 = cx + tw // 2 + pad
        d.rectangle([bx0, line_y - 14, bx1, line_y + 16], fill=COBALT)
        d.text((cx - tw // 2 - bb[0], line_y - 12 - bb[1]), dim_label,
               font=font, fill=WHITE)


def _draw_arrow_label(d: ImageDraw.ImageDraw, *,
                      tail: tuple[int, int], head: tuple[int, int],
                      label: str) -> None:
    """A leader line from `tail` to `head` with an arrowhead at `head`
    and a small mono text label sitting at `tail`."""
    d.line([tail, head], fill=LINE, width=2)
    # arrowhead — small triangle. Compute orientation from delta.
    dx, dy = head[0] - tail[0], head[1] - tail[1]
    # Normalize to a fixed length
    import math
    dist = max(1, math.hypot(dx, dy))
    ux, uy = dx / dist, dy / dist
    a = 14
    # Two side points, perpendicular offset
    px, py = -uy * 7, ux * 7
    p1 = (head[0] - ux * a + px, head[1] - uy * a + py)
    p2 = (head[0] - ux * a - px, head[1] - uy * a - py)
    d.polygon([head, p1, p2], fill=LINE)
    # Label — sits near the tail, offset away from the line
    font = _label_font(22)
    bb = font.getbbox(label)
    tw = bb[2] - bb[0]
    th = bb[3] - bb[1]
    # Background plate for readability
    pad = 8
    lx, ly = tail[0] - tw // 2, tail[1] - th - 22
    d.rectangle([lx - pad, ly - pad, lx + tw + pad, ly + th + pad], fill=COBALT)
    d.text((lx - bb[0], ly - bb[1]), label, font=font, fill=WHITE)


def _draw_top_meta(d: ImageDraw.ImageDraw, *, fig_label: str, topic_name: str) -> None:
    """Top-left FIG. N badge + top-right topic-name technical caption."""
    font = _label_font(22)
    # Top-left
    d.text((SAFE_X, 90), fig_label, font=font, fill=WHITE)
    # Underline tick under the FIG label
    bb = font.getbbox(fig_label)
    d.line([(SAFE_X, 90 + bb[3] + 6), (SAFE_X + (bb[2] - bb[0]), 90 + bb[3] + 6)],
           fill=LINE, width=1)

    # Top-right — topic display name in tech caption + a tiny tick line
    cap = topic_name.upper()
    cap_font = _label_font(20)
    bb = cap_font.getbbox(cap)
    tw = bb[2] - bb[0]
    cx = W - SAFE_X - tw
    d.text((cx, 92), cap, font=cap_font, fill=WHITE)
    d.line([(cx, 92 + bb[3] + 6), (W - SAFE_X, 92 + bb[3] + 6)],
           fill=LINE, width=1)


def _draw_footer(img: Image.Image, *, source: str,
                 slide_num: int, total: int) -> None:
    """Footer rule with source label on the left + slide counter right."""
    d = ImageDraw.Draw(img)
    line_y = H - 110
    # Horizontal rule across the safe area
    d.line([(SAFE_X, line_y), (W - SAFE_X, line_y)], fill=LINE, width=1)
    font = _label_font(22)
    src = f"VIA {source.upper()}"
    d.text((SAFE_X, line_y + 18), src, font=font, fill=WHITE_DIM)
    counter = f"{slide_num:02d} / {total:02d}"
    bb = font.getbbox(counter)
    d.text((W - SAFE_X - (bb[2] - bb[0]), line_y + 18), counter,
           font=font, fill=WHITE_DIM)


# ── headline ───────────────────────────────────────────────────────────────


def _draw_headline(img: Image.Image, title: str) -> None:
    """All-caps Bebas headline anchored to HEADLINE_TOP, balanced wrap.
    Auto-fits the largest size that doesn't overflow."""
    text = punchy(title).upper()
    avail_w = W - SAFE_X * 2
    avail_h = HEADLINE_BOTTOM - HEADLINE_TOP
    chosen_font = None
    chosen_lines: list[str] = []
    for size in (130, 118, 106, 96, 88, 80, 72, 66):
        f = _headline_font(size)
        max_lines = max(2, min(4, avail_h // (size + 8)))
        lines = balanced_wrap(text, f, max_w=avail_w, max_lines=max_lines)
        if not lines:
            continue
        widest = max(f.getbbox(ln)[2] - f.getbbox(ln)[0] for ln in lines)
        line_h = f.getbbox("Hg")[3] + 8
        if widest <= avail_w and line_h * len(lines) <= avail_h:
            chosen_font, chosen_lines = f, lines
            break
    if chosen_font is None:
        chosen_font = _headline_font(70)
        chosen_lines = balanced_wrap(text, chosen_font, max_w=avail_w, max_lines=3) or [text]

    line_h = chosen_font.getbbox("Hg")[3] + 8
    block_h = line_h * len(chosen_lines)
    y = HEADLINE_TOP + (avail_h - block_h) // 2

    d = ImageDraw.Draw(img)
    for ln in chosen_lines:
        bb = chosen_font.getbbox(ln)
        tw = bb[2] - bb[0]
        x = (W - tw) // 2 - bb[0]
        d.text((x, y), ln, font=chosen_font, fill=WHITE)
        y += line_h


# ── inset view: smaller schematic of the same subject ─────────────────────


def _draw_inset(img: Image.Image, line_art: Image.Image,
                *, anchor: tuple[int, int],
                size: tuple[int, int], label: str) -> None:
    """Place a scaled-down version of the line-art in the corner with a
    bracket frame + label, like the 'detail view A' on a real drawing."""
    iw, ih = size
    inset = line_art.copy()
    # Crop to centre square (inset views look balanced as squares)
    side = min(inset.width, inset.height)
    left = (inset.width - side) // 2
    top = (inset.height - side) // 2
    inset = inset.crop((left, top, left + side, top + side))
    inset = inset.resize((iw, ih), Image.LANCZOS)

    base = img.convert("RGBA")
    ax, ay = anchor
    base.alpha_composite(inset, (ax, ay))
    img.paste(base.convert("RGB"))

    d = ImageDraw.Draw(img)
    # Frame brackets
    _draw_corner_brackets(d, (ax, ay, ax + iw, ay + ih), length=22, width=3)
    # Label below the frame
    font = _label_font(18)
    bb = font.getbbox(label)
    d.text((ax, ay + ih + 14 - bb[1]), label, font=font, fill=WHITE_DIM)


# ── full slide composition ────────────────────────────────────────────────


def _slide(article: Article, photo_path: str | None,
           slide_num: int, total: int, topic: TopicConfig,
           output_dir: Path) -> str:
    img = Image.new("RGB", (W, H), COBALT)
    _paint_grid(img)

    # Photo region box (centred horizontally with side margin)
    region_x0 = SAFE_X + 30
    region_y0 = PHOTO_TOP
    region_x1 = W - SAFE_X - 30
    region_y1 = PHOTO_BOTTOM
    region_w = region_x1 - region_x0
    region_h = region_y1 - region_y0

    line_art = None
    if photo_path and os.path.exists(photo_path):
        try:
            photo = Image.open(photo_path).convert("RGB")
            line_art = _to_line_art(photo, target_w=region_w, target_h=region_h)
            base = img.convert("RGBA")
            base.alpha_composite(line_art, (region_x0, region_y0))
            img.paste(base.convert("RGB"))
        except Exception as e:
            log.warning("line-art conversion failed: %s", e)

    d = ImageDraw.Draw(img)

    # Decorations on the photo region
    _draw_corner_brackets(d, (region_x0, region_y0, region_x1, region_y1),
                          length=46, width=4)
    _draw_dimension_ticks(d, (region_x0, region_y0, region_x1, region_y1),
                          dim_label=f"{region_w} × {region_h} px")

    # Arrow + label pointing at the subject from the upper-right gutter.
    # Tail sits in the empty space between the FIG. labels and the photo
    # region's top edge; head lands on the centre of the subject area.
    cx = (region_x0 + region_x1) // 2
    cy = (region_y0 + region_y1) // 2
    _draw_arrow_label(
        d,
        tail=(region_x1 + 10, region_y0 - 90),
        head=(cx + 60, cy - 240),
        label="SUBJECT 01",
    )

    # Top labels
    _draw_top_meta(d, fig_label=f"FIG. {slide_num:02d}",
                   topic_name=topic.display_name or topic.slug)

    # Headline + footer
    _draw_headline(img, article.title)
    _draw_footer(img, source=article.source, slide_num=slide_num, total=total)

    # Body summary — up to 3 lines so the slide carries the actual news,
    # not a one-line tease. Stays subtle (mono label font) to fit the
    # technical-drawing aesthetic of this design.
    if article.description:
        desc = clean_description(article.description, max_chars=240)
        if desc:
            font = _label_font(24)
            from core.typography import balanced_wrap as _bw
            body_lines = _bw(desc, font, max_w=W - SAFE_X * 2, max_lines=3)[:3]
            line_h = font.getbbox("Hg")[3] + 8
            block_h = line_h * len(body_lines)
            y = H - 170 - block_h
            for ln in body_lines:
                bb = font.getbbox(ln)
                d.text(((W - (bb[2] - bb[0])) // 2 - bb[0], y),
                       ln, font=font, fill=WHITE_DIM)
                y += line_h

    out_path = output_dir / f"slide_{slide_num}.png"
    img.save(out_path, "PNG", quality=95)
    return str(out_path)


def render(topic: TopicConfig, articles: list[Article],
           output_dir: Path) -> list[str]:
    """One blueprint slide per article — no hook, no CTA, mirrors the
    `tiktok_news` cadence."""
    output_dir.mkdir(parents=True, exist_ok=True)
    img_dir = output_dir / "_images"
    local_imgs = download_images_parallel(
        [a.image_url or None for a in articles], img_dir,
    )
    total = len(articles)
    paths: list[str] = []
    for i, (art, local) in enumerate(zip(articles, local_imgs), start=1):
        log.info("blueprint %d/%d · %s", i, total, art.source)
        paths.append(_slide(art, local, i, total, topic, output_dir))
    return paths


blueprint = Design(
    slug="blueprint",
    name="Blueprint",
    description=(
        "Single-subject technical-drawing poster. Edge-detected white "
        "linework on deep cobalt with an engineering grid, corner "
        "brackets, dimension ticks, leader arrow, and a small inset "
        "detail view. Bebas headline + monospaced labels."
    ),
    render=render,
)

"""Image helpers shared across designs.

Three responsibilities:
  - `smart_cover`: saliency-aware cover-fit (so faces don't get sliced off)
  - `region_luminance`: cheap brightness probe of a rectangle on a slide
  - `darken_band_under_text`: lay a soft gradient scrim under text only
    when the photo behind it is too bright for white type to be readable

All built on plain Pillow + stdlib — no opencv / mediapipe.
"""
from __future__ import annotations

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageStat


def _saliency_offset(img: Image.Image, *, target_w: int, target_h: int,
                     samples: int = 64) -> tuple[float, float]:
    """Return (cx, cy) in [0, 1] coordinates of the most "interesting" point.

    Uses gradient variance as a cheap stand-in for visual saliency: a sliding
    window scans the downsized grayscale + Sobel-ish image and we pick the
    window with the highest mean. This catches faces, logos, scoreboards —
    anything with high local detail.
    """
    iw, ih = img.size
    src_ratio = iw / ih
    dst_ratio = target_w / target_h

    if src_ratio > dst_ratio:
        # Horizontal slack — search along x.
        crop_w = int(ih * dst_ratio)
        if crop_w >= iw:
            return 0.5, 0.5
        small = img.convert("L").resize((samples, max(1, samples * ih // iw)), Image.BOX)
        edge = small.filter(ImageFilter.FIND_EDGES)
        win = max(1, samples * crop_w // iw)
        best_x, best_score = 0, -1.0
        for x in range(0, samples - win + 1):
            score = ImageStat.Stat(edge.crop((x, 0, x + win, edge.height))).mean[0]
            if score > best_score:
                best_score, best_x = score, x
        cx = (best_x + win / 2) / samples
        return min(max(cx, 0.0), 1.0), 0.5
    else:
        # Vertical slack — search along y.
        crop_h = int(iw / dst_ratio)
        if crop_h >= ih:
            return 0.5, 0.5
        small = img.convert("L").resize((max(1, samples * iw // ih), samples), Image.BOX)
        edge = small.filter(ImageFilter.FIND_EDGES)
        win = max(1, samples * crop_h // ih)
        best_y, best_score = 0, -1.0
        for y in range(0, samples - win + 1):
            score = ImageStat.Stat(edge.crop((0, y, edge.width, y + win))).mean[0]
            if score > best_score:
                best_score, best_y = score, y
        cy = (best_y + win / 2) / samples
        # Bias slightly upward — heads usually live in the top third.
        cy = max(0.18, cy * 0.85 + 0.5 * 0.15)
        return 0.5, min(max(cy, 0.0), 1.0)


def _denoise_and_sharpen_for_upscale(img: Image.Image) -> Image.Image:
    """When we're about to upscale a small JPEG by 2× or more, a tiny
    pre-blur kills the JPEG's blocky edges and a post-sharpen restores
    perceived crispness. Cheap and dramatically less "soup-like" than a
    naked LANCZOS resize.
    """
    img = img.filter(ImageFilter.GaussianBlur(0.6))
    img = ImageEnhance.Sharpness(img).enhance(1.6)
    return img


def smart_cover(img: Image.Image, w: int, h: int, *, prefer_top: bool = True) -> Image.Image:
    """Cover-fit with saliency-aware focal point.

    `prefer_top` keeps the historical bias of news-photo crops: when the photo
    is portrait we favour the upper half (where heads tend to be).

    Small sources (< 1000 px wide) get a light denoise + sharpen pass so
    the LANCZOS upscale doesn't expose JPEG block artifacts.
    """
    iw, ih = img.size
    src_ratio, dst_ratio = iw / ih, w / h
    cx, cy = _saliency_offset(img, target_w=w, target_h=h)

    if src_ratio > dst_ratio:
        new_w = int(ih * dst_ratio)
        x0 = int((iw - new_w) * cx)
        x0 = max(0, min(iw - new_w, x0))
        img = img.crop((x0, 0, x0 + new_w, ih))
    else:
        new_h = int(iw / dst_ratio)
        bias = 0.0 if not prefer_top else -0.05
        y0 = int((ih - new_h) * (cy + bias))
        y0 = max(0, min(ih - new_h, y0))
        img = img.crop((0, y0, iw, y0 + new_h))

    # Pre-clean the source if we're about to bump it up significantly.
    if img.width < max(1000, int(w * 0.9)):
        img = _denoise_and_sharpen_for_upscale(img)

    return img.resize((w, h), Image.LANCZOS)


# ── Contrast / readability helpers ─────────────────────────────────────────


def is_press_photograph(image_path: str) -> bool:
    """Heuristic: return False when the file at `image_path` looks like a
    logo, crest, infographic, badge, or multi-subject composite — i.e.
    not a real photograph.

    Why this exists: aggregated football news (Football.London,
    FourFourTwo, etc.) frequently uses team-crest graphics and
    side-by-side player composites instead of press shots. Those land in
    the carousel as visually dead slides ("Manchester City consider new
    signing" + a flat blue crest). We measure two cheap signals on a
    150×150 thumbnail of the source:

      • *unique colour count* — real photos have thousands of distinct
        colours after JPEG; crests have a handful; gradient logos sit in
        the few-hundred range.
      • *edge mean* — photographs sit in a comfortable middle band of
        gradient density. Flat backgrounds (logos, single-subject
        promos with negative space) come in well below; collage-style
        composites with hard outlines come in well above.

    Fails open: if the file can't be read, we return True and let the
    download verifier handle the broader case. This avoids dropping
    legitimate articles when Pillow has a hiccup on a weird JPEG.
    """
    try:
        with Image.open(image_path) as img:
            if img.width < 400 or img.height < 250:
                return False
            img = img.convert("RGB")
            small = img.resize((150, 150), Image.LANCZOS)

            colors = small.getcolors(maxcolors=150 * 150)
            n_unique = len(colors) if colors else 150 * 150
            edges = small.filter(ImageFilter.FIND_EDGES).convert("L")
            edge_mean = ImageStat.Stat(edges).mean[0]

            # Threshold tuned aggressively for "definite logo / crest /
            # wordmark" only. Real press photos with a smooth bokeh field
            # background clear 1200 after JPEG, single-player portraits
            # clear 2000, action shots clear 4000+. We keep this bar low
            # so real photos always survive, even if the occasional
            # gradient promo slips through.
            if n_unique < 600:
                return False

            # "Definitely flat graphic": almost no gradient detail and
            # very little colour variance. Both signals must point the
            # same way before we drop the article.
            if n_unique < 1000 and edge_mean < 5:
                return False

            # No upper edge bound — crowd shots, action photos, and busy
            # compositions all spike edge density above any threshold a
            # logo wouldn't already hit on the colour-count check.
            return True
    except Exception:
        return True


def punch(img: Image.Image, *, contrast: float = 1.18, saturation: float = 1.15,
          sharpness: float = 1.45) -> Image.Image:
    """Press-photo enhancement: contrast + saturation + crispness so
    RSS/og:image thumbnails read with the same pop as press-service shots.

    Defaults bumped after side-by-side comparison with @f1newsflash —
    their photos run hotter on contrast and noticeably crisper than a
    raw og:image. Push too far and faces start looking plastic, so the
    sharpness is the knob most likely to need tweaking per topic.
    """
    if img.mode != "RGB":
        img = img.convert("RGB")
    if contrast != 1.0:
        img = ImageEnhance.Contrast(img).enhance(contrast)
    if saturation != 1.0:
        img = ImageEnhance.Color(img).enhance(saturation)
    if sharpness != 1.0:
        img = ImageEnhance.Sharpness(img).enhance(sharpness)
    return img


def region_luminance(img: Image.Image, box: tuple[int, int, int, int]) -> float:
    """Mean perceptual luminance (0–255) of an axis-aligned rectangle."""
    x0, y0, x1, y1 = box
    x0 = max(0, x0); y0 = max(0, y0)
    x1 = min(img.width, x1); y1 = min(img.height, y1)
    if x1 <= x0 or y1 <= y0:
        return 128.0
    crop = img.crop((x0, y0, x1, y1)).convert("L")
    return ImageStat.Stat(crop).mean[0]


def darken_band_under_text(
    img: Image.Image,
    box: tuple[int, int, int, int],
    *,
    threshold: float = 110.0,
    max_strength: float = 0.55,
    feather_px: int = 24,
) -> bool:
    """If the photo region behind `box` is bright enough that white text would
    fight the background, lay a feathered dark gradient *only there*.

    Returns True when the band was applied. Designs typically call this once
    per slide right before they draw the headline so they don't have to
    care about per-photo brightness.

    Implementation: sample the region's mean luminance, scale a black
    overlay's opacity proportionally to how far above the threshold we are,
    and feather the rectangle's edges so the band looks intentional.
    """
    lum = region_luminance(img, box)
    if lum <= threshold:
        return False
    # 0 at threshold → max_strength at fully white
    overdrive = (lum - threshold) / max(1.0, 255.0 - threshold)
    strength = min(max_strength, max_strength * overdrive)
    if strength <= 0.05:
        return False

    x0, y0, x1, y1 = box
    pad = feather_px
    rect = (
        max(0, x0 - pad),
        max(0, y0 - pad),
        min(img.width, x1 + pad),
        min(img.height, y1 + pad),
    )
    rw, rh = rect[2] - rect[0], rect[3] - rect[1]
    if rw <= 0 or rh <= 0:
        return False

    band = Image.new("RGBA", (rw, rh), (0, 0, 0, 0))
    bd = ImageDraw.Draw(band)
    bd.rounded_rectangle(
        [pad, pad, rw - pad, rh - pad],
        radius=12,
        fill=(0, 0, 0, int(255 * strength)),
    )
    band = band.filter(ImageFilter.GaussianBlur(feather_px / 2))

    base = img if img.mode == "RGBA" else img.convert("RGBA")
    base.alpha_composite(band, (rect[0], rect[1]))
    if img.mode != "RGBA":
        # mutate `img` in-place so callers don't have to swap their reference
        img.paste(base.convert("RGB"))
    return True

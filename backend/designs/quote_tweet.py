"""Quote-Tweet design — every slide looks like a screenshot of a single
X / Twitter post.

The hook here is "native-looking content." TikTok viewers scroll past
photo-with-headline carousels because they look like ads; they slow down
on what looks like a tweet because tweets read as primary sources. Each
slide is one article presented as a fake tweet:

  ┌─────────────────────────────────┐
  │  ⬢  F1 Daily ✓                  │  ← avatar (topic emblem) + handle row
  │     @f1daily · 2h               │
  │                                 │
  │  Russell wins the Canadian      │  ← article title styled as tweet body
  │  Grand Prix Sprint after        │     (sentence case, conversational)
  │  clashing with Antonelli.       │
  │                                 │
  │  ┌─────────────────────────┐    │
  │  │                         │    │  ← rounded media card with article
  │  │   <article hero photo>  │    │     hero photo (16:9)
  │  │                         │    │
  │  └─────────────────────────┘    │
  │                                 │
  │  ♡ 23K   ↻ 8.4K   💬 1.2K       │  ← engagement counters
  │                                 │
  │  4:02 PM · May 19, 2026 · 234K  │  ← timestamp + view count
  └─────────────────────────────────┘

Slides 1..N: one article per slide.
Slide N+1:   CTA — same tweet layout, but body says "Follow for more"
             and the embedded image is a brand backdrop.
"""
from __future__ import annotations

import hashlib
import os
import random
import re
from datetime import datetime, timedelta
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from core.http import download_images_parallel
from core.image import smart_cover
from core.log import get_logger
from core.parsers.base import Article
from core.text import clean_description, clean_headline
from core.topic_loader import TopicConfig
from core.typography import balanced_wrap

from designs.base import Design

log = get_logger("design.quote_tweet")

CORE_FONTS = Path(__file__).resolve().parent.parent / "core" / "assets" / "fonts"
FALLBACK_HEADLINE = str(CORE_FONTS / "Anton-Regular.ttf")
FALLBACK_BODY = str(CORE_FONTS / "BebasNeue-Regular.ttf")

# X/Twitter uses Chirp; we approximate with the closest system sans-serif.
# These are macOS paths — on Linux we'd fall back to DejaVu/Liberation.
TWEET_FONT_CANDIDATES = (
    "/System/Library/Fonts/HelveticaNeue.ttc",
    "/System/Library/Fonts/SFCompact.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
)

# X palette (dark theme — most engaging on TikTok in 2026)
TWEET_BG = (15, 20, 25)        # near-black with a hint of blue
TWEET_TEXT = (231, 233, 234)    # near-white body text
TWEET_MUTED = (113, 118, 123)   # @handle, timestamps, counters
TWEET_DIVIDER = (47, 51, 54)    # hairlines between sections
TWEET_BORDER = (47, 51, 54)     # card border around the embedded media
ACCENT_BLUE = (29, 155, 240)    # X / Twitter blue for the verified badge
WHITE = (255, 255, 255)


def _tweet_font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Resolve a system sans-serif close to Twitter's Chirp.

    HelveticaNeue.ttc holds multiple variants; PIL picks the regular
    face by default. For bold, we ask for index=1 (HelveticaNeue Bold
    on macOS — falls through to other faces on different systems)."""
    for p in TWEET_FONT_CANDIDATES:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size, index=1 if bold else 0)
            except OSError:
                try:
                    return ImageFont.truetype(p, size)
                except OSError:
                    continue
    return ImageFont.load_default()


# ── deterministic fake engagement numbers ─────────────────────────────────


def _fake_engagement(article: Article) -> dict:
    """Produce plausible like / repost / reply / view counts for the
    fake tweet. Seeded on article URL so the same article always shows
    the same numbers across re-renders (carousel feels consistent)."""
    seed = int(hashlib.sha1(article.url.encode("utf-8")).hexdigest()[:8], 16)
    r = random.Random(seed)

    # Views: 50K–500K with a long tail
    views_raw = int(r.gauss(180_000, 90_000))
    views = max(15_000, min(900_000, views_raw))
    # Likes ≈ 5-15% of views
    likes = int(views * r.uniform(0.04, 0.14))
    # Reposts ≈ 30-50% of likes
    reposts = int(likes * r.uniform(0.25, 0.55))
    # Replies ≈ 8-20% of likes
    replies = int(likes * r.uniform(0.08, 0.22))
    return {
        "views": views, "likes": likes, "reposts": reposts, "replies": replies,
    }


def _human_count(n: int) -> str:
    """Format like Twitter: 23000 → 23K, 1234567 → 1.2M."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M".rstrip("0").rstrip(".")
    if n >= 1_000:
        return f"{n / 1_000:.1f}K".rstrip("0").rstrip(".")
    return str(n)


def _fake_timestamp(article: Article) -> str:
    """`4:02 PM · May 19, 2026` — seeded so a given article always
    shows the same time. Pick a timestamp 1-12 hours before now so
    'recent activity' feel is consistent."""
    seed = int(hashlib.sha1(article.url.encode("utf-8")).hexdigest()[8:16], 16)
    r = random.Random(seed)
    hours_ago = r.randint(1, 12)
    minutes_offset = r.randint(0, 59)
    ts = datetime.now() - timedelta(hours=hours_ago, minutes=minutes_offset)
    # Twitter style: lowercase am/pm joined, then date, all separated by ·
    time_part = ts.strftime("%-I:%M %p")
    date_part = ts.strftime("%b %-d, %Y")
    return f"{time_part} · {date_part}"


def _handle_for_topic(topic: TopicConfig) -> tuple[str, str]:
    """Convert topic display name into (display, @handle) pair.
    Removes 'Daily' suffix from display, lowercases handle, strips
    spaces — so 'F1 Daily' → ('F1 Daily', '@f1daily')."""
    display = topic.display_name or topic.slug
    handle = re.sub(r"[^a-z0-9]", "", display.lower())
    return display, f"@{handle}"


# ── per-element renderers ─────────────────────────────────────────────────


def _draw_avatar(canvas: Image.Image, *, topic: TopicConfig,
                 x: int, y: int, size: int) -> None:
    """Round avatar: brand-coloured disc with topic initial.
    Approximates the role of a profile picture in a real tweet."""
    accent = topic.brand.accent or (29, 155, 240)
    avatar = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(avatar)
    d.ellipse([0, 0, size - 1, size - 1], fill=accent + (255,))

    label = (topic.display_name or topic.slug or "").strip().upper()
    label = label[:2] if len(label) <= 4 else label[:1]
    headline_path = topic.brand.font_headline or FALLBACK_HEADLINE
    try:
        f = ImageFont.truetype(headline_path, int(size * 0.5))
    except OSError:
        f = ImageFont.truetype(FALLBACK_HEADLINE, int(size * 0.5))
    bb = f.getbbox(label)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    d.text((size // 2 - tw // 2 - bb[0],
            size // 2 - th // 2 - bb[1] - 4),
           label, font=f, fill=WHITE)

    base = canvas.convert("RGBA")
    base.alpha_composite(avatar, (x, y))
    canvas.paste(base.convert("RGB"))


def _draw_verified_badge(d: ImageDraw.ImageDraw, *, x: int, y: int,
                         size: int) -> None:
    """Tiny circular blue checkmark next to the display name."""
    d.ellipse([x, y, x + size, y + size], fill=ACCENT_BLUE)
    # Approximate the checkmark with three line segments
    cx, cy = x + size // 2, y + size // 2
    s = size // 4
    d.line([(cx - s, cy), (cx - s // 3, cy + s // 2 + 1),
            (cx + s, cy - s // 2)], fill=WHITE, width=max(2, size // 8))


def _draw_media_card(canvas: Image.Image, *, photo_path: str | None,
                     x: int, y: int, w: int, h: int) -> None:
    """Rounded-corner embedded media card. Twitter clips images to a
    16:9-ish ratio with rounded corners and a hairline border."""
    radius = 22
    border_col = TWEET_BORDER

    if not photo_path or not os.path.exists(photo_path):
        # Placeholder: flat dark card
        placeholder = Image.new("RGB", (w, h), (30, 35, 40))
        photo = placeholder
    else:
        try:
            photo = Image.open(photo_path).convert("RGB")
            photo = smart_cover(photo, w, h, prefer_top=True)
        except Exception as e:
            log.warning("media card photo failed: %s", e)
            photo = Image.new("RGB", (w, h), (30, 35, 40))

    # Mask for rounded corners
    mask = Image.new("L", (w, h), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle([0, 0, w, h], radius=radius, fill=255)

    base = canvas.convert("RGBA")
    photo_rgba = photo.convert("RGBA")
    photo_rgba.putalpha(mask)
    base.alpha_composite(photo_rgba, (x, y))

    # Hairline border around the rounded card (1px feels right at 1080w)
    od = ImageDraw.Draw(base)
    od.rounded_rectangle([x, y, x + w, y + h], radius=radius,
                          outline=border_col + (255,), width=1)
    canvas.paste(base.convert("RGB"))


def _draw_engagement_row(d: ImageDraw.ImageDraw, *, x: int, y: int,
                         counts: dict, font: ImageFont.FreeTypeFont) -> None:
    """`♡ 23K   ↻ 8.4K   💬 1.2K   📊 234K` row."""
    icon_color = TWEET_MUTED
    items = [
        ("💬", _human_count(counts["replies"])),
        ("↻", _human_count(counts["reposts"])),
        ("♡", _human_count(counts["likes"])),
        ("📊", _human_count(counts["views"])),
    ]
    cur_x = x
    for icon, text in items:
        # Render the icon + text with small gap
        d.text((cur_x, y), f"{icon}  {text}", font=font, fill=icon_color)
        # Advance: measured width + spacer
        bb = font.getbbox(f"{icon}  {text}")
        w = bb[2] - bb[0]
        cur_x += w + 60


# ── tweet body text ───────────────────────────────────────────────────────


def _tweet_text(article: Article) -> str:
    """Convert article title into a tweet-style body string.

    Real tweets are sentence-case, conversational, end with a period or
    no punctuation at all. Article titles are often Title Case from RSS
    feeds. We normalise: keep proper-noun-style capitalisation but
    lowercase common words so it reads natural.
    """
    title = clean_headline(article.title).strip()
    # If title is ALL CAPS, normalise to sentence case
    if title and title == title.upper() and len(title) > 6:
        words = title.split()
        out = [words[0].capitalize()]
        for w in words[1:]:
            # Keep multi-cap acronyms (NBA, F1, NHL) as-is once they're
            # already short enough; lowercase the rest.
            if len(w) <= 4 and w.isalpha() and w.isupper():
                out.append(w)
            else:
                out.append(w.lower())
        title = " ".join(out)
        # Re-capitalise team/league acronyms by simple heuristic
        for acronym in ("NBA", "NFL", "NHL", "MLB", "UFC", "WWE", "WNBA",
                        "PGA", "ATP", "WTA", "ICC", "IPL", "IOC", "F1",
                        "NCAA", "MMA", "MVP", "GOAT", "PSG", "AC"):
            title = re.sub(rf"\b{acronym.lower()}\b", acronym, title)
    if not title.endswith((".", "!", "?")):
        title += "."
    return title


# ── slide assembly ────────────────────────────────────────────────────────


def _render_tweet_slide(article: Article, photo_path: str | None,
                        topic: TopicConfig, slide_num: int, total: int,
                        W: int, H: int) -> Image.Image:
    """One tweet-styled slide. Layout from top:
        margin → header (avatar + name row) → tweet body → media card
        → engagement row → timestamp → counter pill bottom-right."""
    img = Image.new("RGB", (W, H), TWEET_BG)
    d = ImageDraw.Draw(img)

    margin = 56            # comfortable safe-zone inside the slide
    cur_y = margin

    # ── HEADER (avatar + display name + handle + time) ────────────────
    avatar_size = 100
    _draw_avatar(img, topic=topic, x=margin, y=cur_y, size=avatar_size)
    d = ImageDraw.Draw(img)  # re-fetch after paste

    display, handle = _handle_for_topic(topic)
    header_x = margin + avatar_size + 24

    name_font = _tweet_font(40, bold=True)
    handle_font = _tweet_font(32)
    d.text((header_x, cur_y + 4), display, font=name_font, fill=TWEET_TEXT)
    # Verified badge tight to the display name
    bb = name_font.getbbox(display)
    name_w = bb[2] - bb[0]
    badge_x = header_x + name_w + 12
    badge_y = cur_y + 14
    _draw_verified_badge(d, x=badge_x, y=badge_y, size=32)

    # Handle on second line, muted colour
    d.text((header_x, cur_y + 56), handle, font=handle_font, fill=TWEET_MUTED)

    cur_y += avatar_size + 28

    # ── BODY (the tweet text — our article title) ─────────────────────
    body = _tweet_text(article)
    body_font = _tweet_font(46)
    body_lines = balanced_wrap(body, body_font, max_w=W - margin * 2,
                               max_lines=4)
    body_line_h = body_font.getbbox("Hg")[3] + 10
    for ln in body_lines:
        d.text((margin, cur_y), ln, font=body_font, fill=TWEET_TEXT)
        cur_y += body_line_h
    cur_y += 24  # gap before media card

    # ── MEDIA CARD (article photo, rounded) ───────────────────────────
    # Reserve enough room for engagement row + timestamp + counter below.
    bottom_reserve = 200
    card_x = margin
    card_w = W - margin * 2
    card_h = max(100, H - cur_y - bottom_reserve)
    # Cap the card aspect ratio at 16:9 so it doesn't dominate the slide.
    max_card_h = int(card_w * 9 / 16) + 80
    if card_h > max_card_h:
        card_h = max_card_h
    _draw_media_card(img, photo_path=photo_path,
                     x=card_x, y=cur_y, w=card_w, h=card_h)
    cur_y += card_h + 28
    d = ImageDraw.Draw(img)

    # ── ENGAGEMENT ROW (♡ ↻ 💬 📊) ────────────────────────────────────
    counts = _fake_engagement(article)
    eng_font = _tweet_font(28)
    _draw_engagement_row(d, x=margin, y=cur_y, counts=counts, font=eng_font)
    cur_y += 36

    # ── TIMESTAMP ────────────────────────────────────────────────────
    ts = _fake_timestamp(article)
    ts_font = _tweet_font(24)
    d.text((margin, cur_y + 12), ts, font=ts_font, fill=TWEET_MUTED)

    # ── COUNTER PILL (bottom-right) ───────────────────────────────────
    counter_font = _tweet_font(22)
    counter = f"{slide_num:02d} / {total:02d}"
    cb = counter_font.getbbox(counter)
    cw = cb[2] - cb[0]
    pad = 12
    pill_h = cb[3] - cb[1] + 12
    x1 = W - margin
    y1 = H - 28
    x0 = x1 - cw - pad * 2
    y0 = y1 - pill_h
    d.rounded_rectangle([x0, y0, x1, y1], radius=pill_h // 2,
                         fill=TWEET_DIVIDER)
    d.text((x0 + pad,
            y0 + (pill_h - (cb[3] - cb[1])) // 2 - cb[1]),
           counter, font=counter_font, fill=TWEET_MUTED)

    return img


def _render_cta_tweet(topic: TopicConfig, slide_num: int, total: int,
                      W: int, H: int) -> Image.Image:
    """Final slide: same tweet layout, but the body is the follow-prompt
    and the media card is a brand backdrop instead of a photo."""
    img = Image.new("RGB", (W, H), TWEET_BG)
    d = ImageDraw.Draw(img)

    margin = 56
    cur_y = margin

    avatar_size = 100
    _draw_avatar(img, topic=topic, x=margin, y=cur_y, size=avatar_size)
    d = ImageDraw.Draw(img)

    display, handle = _handle_for_topic(topic)
    header_x = margin + avatar_size + 24
    name_font = _tweet_font(40, bold=True)
    handle_font = _tweet_font(32)
    d.text((header_x, cur_y + 4), display, font=name_font, fill=TWEET_TEXT)
    bb = name_font.getbbox(display)
    _draw_verified_badge(d, x=header_x + (bb[2] - bb[0]) + 12,
                         y=cur_y + 14, size=32)
    d.text((header_x, cur_y + 56), handle, font=handle_font, fill=TWEET_MUTED)
    cur_y += avatar_size + 28

    body_lines = [
        "We post the day's biggest stories.",
        f"Follow {handle} so you don't miss them.",
    ]
    body_font = _tweet_font(46)
    body_line_h = body_font.getbbox("Hg")[3] + 10
    for ln in body_lines:
        d.text((margin, cur_y), ln, font=body_font, fill=TWEET_TEXT)
        cur_y += body_line_h
    cur_y += 24

    # Brand media card instead of photo
    bottom_reserve = 200
    card_x, card_w = margin, W - margin * 2
    card_h = min(int(card_w * 9 / 16) + 80, H - cur_y - bottom_reserve)
    accent = topic.brand.accent or (29, 155, 240)
    card = Image.new("RGB", (card_w, card_h), accent)
    cd = ImageDraw.Draw(card)
    label_font = _tweet_font(120, bold=True)
    label = "FOLLOW"
    lb = label_font.getbbox(label)
    cd.text((card_w // 2 - (lb[2] - lb[0]) // 2 - lb[0],
             card_h // 2 - (lb[3] - lb[1]) // 2 - lb[1] - 4),
            label, font=label_font, fill=WHITE)

    mask = Image.new("L", (card_w, card_h), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle([0, 0, card_w, card_h], radius=22, fill=255)
    base = img.convert("RGBA")
    rgba = card.convert("RGBA")
    rgba.putalpha(mask)
    base.alpha_composite(rgba, (card_x, cur_y))
    img.paste(base.convert("RGB"))
    cur_y += card_h + 28
    d = ImageDraw.Draw(img)

    # Engagement row with big-but-believable numbers for the CTA
    counts = {"views": 423_000, "likes": 38_400, "reposts": 12_100, "replies": 2_900}
    eng_font = _tweet_font(28)
    _draw_engagement_row(d, x=margin, y=cur_y, counts=counts, font=eng_font)
    cur_y += 36

    ts_font = _tweet_font(24)
    d.text((margin, cur_y + 12),
           datetime.now().strftime("%-I:%M %p · %b %-d, %Y"),
           font=ts_font, fill=TWEET_MUTED)

    counter_font = _tweet_font(22)
    counter = f"{slide_num:02d} / {total:02d}"
    cb = counter_font.getbbox(counter)
    cw = cb[2] - cb[0]
    pad = 12
    pill_h = cb[3] - cb[1] + 12
    x1 = W - margin
    y1 = H - 28
    x0 = x1 - cw - pad * 2
    y0 = y1 - pill_h
    d.rounded_rectangle([x0, y0, x1, y1], radius=pill_h // 2,
                         fill=TWEET_DIVIDER)
    d.text((x0 + pad,
            y0 + (pill_h - (cb[3] - cb[1])) // 2 - cb[1]),
           counter, font=counter_font, fill=TWEET_MUTED)

    return img


# ── public render ─────────────────────────────────────────────────────────


def render(topic: TopicConfig, articles: list[Article],
           output_dir: Path) -> list[str]:
    """N article slides (each a fake tweet) + 1 CTA tweet at the end."""
    if not articles:
        return []
    output_dir.mkdir(parents=True, exist_ok=True)
    img_dir = output_dir / "_images"

    local_imgs = download_images_parallel(
        [a.image_url or None for a in articles], img_dir,
    )

    W, H = topic.carousel.width, topic.carousel.height
    n_articles = len(articles)
    n_total = n_articles + 1  # +CTA

    paths: list[str] = []
    for i, (art, photo) in enumerate(zip(articles, local_imgs), start=1):
        log.info("tweet %d/%d · %s", i, n_total, art.source)
        slide = _render_tweet_slide(art, photo, topic, i, n_total, W, H)
        out = output_dir / f"slide_{i}.png"
        slide.save(out, "PNG", quality=92)
        paths.append(str(out))

    log.info("tweet %d/%d · cta", n_total, n_total)
    cta = _render_cta_tweet(topic, n_total, n_total, W, H)
    out = output_dir / f"slide_{n_total}.png"
    cta.save(out, "PNG", quality=92)
    paths.append(str(out))

    return paths


quote_tweet = Design(
    slug="quote_tweet",
    name="Quote Tweet",
    description=(
        "Each slide rendered as a screenshot of a single X/Twitter "
        "post — avatar, verified handle, conversational body, "
        "rounded media card, engagement counters, timestamp. Reads as "
        "primary-source content rather than ad-style carousel, which "
        "slows TikTok scrolling. One article per slide + a follow-CTA "
        "tweet at the end."
    ),
    render=render,
)

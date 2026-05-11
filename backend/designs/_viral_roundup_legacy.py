"""Viral NBA news roundup carousel — 5 stories blowing up. 1080x1920."""
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path

OUT = Path(__file__).parent
PHOTOS = OUT / "photos"
W, H = 1080, 1920

BG = (10, 10, 10)
WHITE = (255, 255, 255)
ORANGE = (255, 107, 26)
GREY = (180, 180, 180)
RED = (220, 30, 30)
DARK_RED = (140, 20, 20)

HN = "/System/Library/Fonts/HelveticaNeue.ttc"


def headline(size):
    return ImageFont.truetype(HN, size, index=9)


def body(size):
    return ImageFont.truetype(HN, size, index=1)


def text_size(draw, s, f):
    l, t, r, b = draw.textbbox((0, 0), s, font=f)
    return r - l, b - t


def centered(draw, y, text, f, color=WHITE):
    w, _ = text_size(draw, text, f)
    draw.text(((W - w) / 2, y), text, font=f, fill=color)


def fit_centered(draw, y, text, font_kind, max_size, color=WHITE, max_w=980):
    size = max_size
    while size > 30:
        f = font_kind(size)
        w, _ = text_size(draw, text, f)
        if w <= max_w:
            break
        size -= 4
    draw.text(((W - w) / 2, y), text, font=f, fill=color)


def accent_bar(draw, color=ORANGE):
    draw.rectangle([(0, H - 12), (W, H)], fill=color)


# --- photo helpers ---

def fit_cover(img, w, h):
    iw, ih = img.size
    src_ratio = iw / ih
    dst_ratio = w / h
    if src_ratio > dst_ratio:
        new_w = int(ih * dst_ratio)
        x0 = (iw - new_w) // 2
        img = img.crop((x0, 0, x0 + new_w, ih))
    else:
        new_h = int(iw / dst_ratio)
        y0 = (ih - new_h) // 2
        img = img.crop((0, y0, iw, y0 + new_h))
    return img.resize((w, h), Image.LANCZOS)


def darken(img, amount):
    overlay = Image.new("RGBA", img.size, (0, 0, 0, int(255 * amount)))
    img = img.convert("RGBA")
    img.alpha_composite(overlay)
    return img.convert("RGB")


def tint(img, color, amount):
    """Apply colored overlay (for dramatic effect — red on scandal)."""
    overlay = Image.new("RGBA", img.size, color + (int(255 * amount),))
    img = img.convert("RGBA")
    img.alpha_composite(overlay)
    return img.convert("RGB")


def photo_bg(photo_name, dark=0.6, tint_color=None, tint_amount=0):
    img = Image.open(PHOTOS / photo_name).convert("RGB")
    img = fit_cover(img, W, H)
    if dark > 0:
        img = darken(img, dark)
    if tint_color and tint_amount > 0:
        img = tint(img, tint_color, tint_amount)
    return img


def circular_avatar(photo_name, size, focus_top=True):
    img = Image.open(PHOTOS / photo_name).convert("RGB")
    iw, ih = img.size
    side = min(iw, ih)
    x0 = (iw - side) // 2
    if focus_top and ih > iw:
        y0 = max(0, (ih - side) // 4)
    else:
        y0 = (ih - side) // 2
    img = img.crop((x0, y0, x0 + side, y0 + side)).resize((size, size), Image.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out


def avatar_with_ring(photo_name, size, ring_color=ORANGE, ring_w=10, focus_top=True):
    inner = size - ring_w * 2
    av = circular_avatar(photo_name, inner, focus_top=focus_top)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(canvas)
    d.ellipse((0, 0, size, size), fill=ring_color)
    canvas.paste(av, (ring_w, ring_w), av)
    return canvas


def new_canvas(color=BG):
    return Image.new("RGB", (W, H), color)


def breaking_badge(d, y=180, label="BREAKING", color=RED):
    f = headline(70)
    pad_x, pad_y = 36, 18
    tw, th = text_size(d, label, f)
    box_w = tw + pad_x * 2
    box_h = th + pad_y * 2
    x = (W - box_w) / 2
    d.rectangle([(x, y), (x + box_w, y + box_h)], fill=color)
    d.text((x + pad_x, y + pad_y - 8), label, font=f, fill=WHITE)


def number_badge(img, num, x=80, y=120, size=200, color=ORANGE):
    """Big rank badge (1, 2, 3, 4, 5) in corner."""
    d = ImageDraw.Draw(img)
    f = headline(size)
    d.text((x, y), f"#{num}", font=f, fill=color)


# ---------- slides ----------

def slide_1():
    """Hook — 5 NBA stories blowing up."""
    img = photo_bg("arena.jpg", dark=0.72)
    d = ImageDraw.Draw(img)

    breaking_badge(d, y=200)

    fit_centered(d, 460, "5 NBA STORIES", headline, 180)
    fit_centered(d, 660, "BLOWING UP", headline, 180, ORANGE)
    fit_centered(d, 840, "RIGHT NOW", headline, 180)

    centered(d, 1140, "From scandals to surprises —", body(54), WHITE)
    centered(d, 1220, "you missed all of these", body(54), WHITE)

    fit_centered(d, 1480, "#1 WILL SHOCK YOU", headline, 90, ORANGE)

    accent_bar(d)
    img.save(OUT / "01_hook.png")


def slide_2():
    """#5 Brad Stevens."""
    img = photo_bg("stevens.jpg", dark=0.62)
    d = ImageDraw.Draw(img)

    number_badge(img, 5)

    fit_centered(d, 360, "BRAD STEVENS", headline, 130, WHITE)
    fit_centered(d, 510, "EXEC OF THE YEAR", headline, 110, ORANGE)
    centered(d, 660, "(for the 2nd time)", body(48), GREY)

    centered(d, 1040, "Lost Tatum to injury —", body(56), WHITE)
    centered(d, 1120, "still built a 56-win team", body(56), WHITE)

    fit_centered(d, 1380, "MASTERMIND IN BOSTON", headline, 90, ORANGE)

    accent_bar(d)
    img.save(OUT / "02_stevens.png")


def slide_3():
    """#4 Steve Kerr future."""
    img = photo_bg("kerr.jpg", dark=0.62)
    d = ImageDraw.Draw(img)

    number_badge(img, 4)

    fit_centered(d, 360, "KERR'S FUTURE", headline, 140, WHITE)
    fit_centered(d, 520, "IS UNCERTAIN", headline, 140, ORANGE)

    centered(d, 940, "No contract extension talks", body(54), WHITE)
    centered(d, 1020, "Warriors missed playoffs", body(54), WHITE)
    centered(d, 1100, "Salary, staff under review", body(54), WHITE)

    fit_centered(d, 1320, "4-TIME CHAMP", headline, 110, ORANGE)
    fit_centered(d, 1450, "ON HIS WAY OUT?", headline, 110, WHITE)

    accent_bar(d)
    img.save(OUT / "03_kerr.png")


def slide_4():
    """#3 Durant out."""
    img = photo_bg("durant.jpg", dark=0.62)
    d = ImageDraw.Draw(img)

    number_badge(img, 3)

    fit_centered(d, 360, "DURANT OUT", headline, 180, WHITE)
    fit_centered(d, 560, "FOR GAME 5", headline, 180, ORANGE)

    centered(d, 920, "Left ankle sprain", body(56), WHITE)
    centered(d, 1000, "+ bone bruise", body(56), WHITE)

    fit_centered(d, 1240, "ROCKETS DOWN 1-3", headline, 110, ORANGE)
    centered(d, 1390, "Win Wednesday — or season ends", body(50), WHITE)

    accent_bar(d)
    img.save(OUT / "04_durant.png")


def slide_5():
    """#2 Cooper Flagg ROY."""
    img = photo_bg("flagg.jpg", dark=0.55)
    d = ImageDraw.Draw(img)

    number_badge(img, 2)

    fit_centered(d, 360, "COOPER FLAGG", headline, 150, WHITE)
    fit_centered(d, 520, "IS ROOKIE", headline, 150, ORANGE)
    fit_centered(d, 680, "OF THE YEAR", headline, 150, ORANGE)

    centered(d, 1040, "#1 overall pick delivers", body(56), WHITE)
    centered(d, 1120, "Breakout debut season", body(56), WHITE)

    fit_centered(d, 1340, "MAVS' FUTURE", headline, 130, ORANGE)
    fit_centered(d, 1480, "IS HERE", headline, 130, WHITE)

    accent_bar(d)
    img.save(OUT / "05_flagg.png")


def slide_6():
    """#1 Damon Jones gambling — text-only with red dramatic styling."""
    img = new_canvas(BG)
    d = ImageDraw.Draw(img)

    # Red BREAKING SCANDAL badge
    breaking_badge(d, y=140, label="SCANDAL")

    number_badge(img, 1, y=320)

    fit_centered(d, 580, "DAMON JONES", headline, 170, WHITE)
    fit_centered(d, 760, "PLEADS GUILTY", headline, 170, RED)

    centered(d, 1040, "First arrest in NBA's biggest", body(54), WHITE)
    centered(d, 1120, "gambling scandal — 30+ charged", body(54), WHITE)

    centered(d, 1320, "Ex-shooting coach", body(50), GREY)
    centered(d, 1390, "to LeBron James", body(50), GREY)

    fit_centered(d, 1560, "UP TO 63 MONTHS", headline, 100, RED)
    fit_centered(d, 1690, "IN PRISON", headline, 100, WHITE)

    accent_bar(d, color=RED)
    img.save(OUT / "06_jones.png")


def slide_7():
    """#1 context — why it matters."""
    img = photo_bg("balls_texture.jpg", dark=0.82)
    d = ImageDraw.Draw(img)

    fit_centered(d, 200, "WHY IT MATTERS", headline, 130, RED)

    blocks = [
        ("INSIDER INFO", "on injured stars used for bets"),
        ("RIGGED POKER", "alongside reputed mobsters"),
        ("FIRST PLEA", "of 30+ NBA-linked arrests"),
    ]
    y = 460
    for big, label in blocks:
        fit_centered(d, y, big, headline, 150, WHITE)
        centered(d, y + 170, label, body(46), GREY)
        y += 340

    accent_bar(d, color=RED)
    img.save(OUT / "07_jones_context.png")


def slide_8():
    """CTA."""
    img = photo_bg("arena.jpg", dark=0.7)
    d = ImageDraw.Draw(img)

    fit_centered(d, 280, "WHICH STORY", headline, 160)
    fit_centered(d, 460, "SHOCKED YOU", headline, 160)
    fit_centered(d, 640, "THE MOST?", headline, 160, ORANGE)

    centered(d, 920, "Drop the number", body(58), WHITE)
    centered(d, 1000, "in the comments", body(58), WHITE)

    centered(d, 1180, "1  »  2  »  3  »  4  »  5", headline(80), ORANGE)

    centered(d, 1430, "FOLLOW »", headline(80), ORANGE)
    centered(d, 1560, "for daily NBA news", body(46), GREY)

    accent_bar(d)
    img.save(OUT / "08_cta.png")


if __name__ == "__main__":
    for fn in [slide_1, slide_2, slide_3, slide_4, slide_5, slide_6, slide_7, slide_8]:
        fn()
        print("✓", fn.__name__)
    print(f"\nDone → {OUT}")

"""Smart-cover saliency tests.

We construct a synthetic image where one corner has dense edges and
verify that `smart_cover` biases the crop window toward that corner.
"""
from PIL import Image, ImageDraw

from core.image import smart_cover


def _busy_corner_image(w: int, h: int, *, corner: str = "right") -> Image.Image:
    img = Image.new("RGB", (w, h), (32, 32, 32))
    d = ImageDraw.Draw(img)
    # Lots of high-frequency lines on the chosen side.
    if corner == "right":
        x0 = int(w * 0.65)
        for y in range(0, h, 6):
            d.line([(x0, y), (w, y)], fill=(240, 240, 240), width=2)
    elif corner == "left":
        x1 = int(w * 0.35)
        for y in range(0, h, 6):
            d.line([(0, y), (x1, y)], fill=(240, 240, 240), width=2)
    return img


def test_smart_cover_biases_toward_busy_side():
    src = _busy_corner_image(2000, 1000, corner="right")
    out = smart_cover(src, 800, 1000, prefer_top=False)
    # Compare brightness of left vs right halves of the cropped output —
    # the crop should have pulled the busy half into frame.
    w, h = out.size
    left = out.crop((0, 0, w // 2, h))
    right = out.crop((w // 2, 0, w, h))
    # mean luminance via Pillow's getextrema-style sum
    def lum(im):
        gx = im.convert("L")
        s = sum(gx.getdata())
        return s / (gx.width * gx.height)
    assert lum(right) > lum(left), "expected smart crop to favour the busy half"


def test_smart_cover_pure_passthrough_when_aspect_matches():
    src = Image.new("RGB", (800, 1000), (50, 50, 50))
    out = smart_cover(src, 800, 1000)
    assert out.size == (800, 1000)

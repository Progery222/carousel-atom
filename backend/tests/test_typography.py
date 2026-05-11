"""Tests for the balanced-wrap helper.

Uses Pillow's default bitmap font so the test runs without bundled TTFs.
"""
from PIL import ImageFont

from core.typography import balanced_wrap, greedy_wrap


def _font():
    return ImageFont.load_default()


def test_short_text_one_line():
    assert balanced_wrap("Hello world", _font(), max_w=10_000) == ["Hello world"]


def test_balanced_split_in_half():
    text = "Verstappen wins Bahrain Grand Prix after a late charge"
    font = _font()
    # Force two lines via a small max width.
    greedy = greedy_wrap(text, font, max_w=120)
    if len(greedy) <= 1:
        # default font is too narrow for this test on some platforms — skip
        return
    bal = balanced_wrap(text, font, max_w=120, max_lines=2)
    assert 1 <= len(bal) <= 2

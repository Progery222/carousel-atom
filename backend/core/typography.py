"""Typography helpers shared across designs.

The original `_wrap_to_width` is greedy and produces ugly widow lines like

    THIS HEADLINE IS A LITTLE
    LONG

Instead we use a balanced wrap: greedy first to know how many lines we
need, then re-flow words so each line ends up roughly the same width.

Also exposes `fit_font` — binary-search the largest font size that fits
the wrapped headline inside a target box, with `max_lines` as a hard cap.
"""
from __future__ import annotations

from PIL import ImageFont


def _measure(font: ImageFont.FreeTypeFont, text: str) -> int:
    if not text:
        return 0
    bb = font.getbbox(text)
    return bb[2] - bb[0]


def greedy_wrap(text: str, font: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current: list[str] = []
    for w in words:
        trial = " ".join(current + [w])
        if _measure(font, trial) > max_w and current:
            lines.append(" ".join(current))
            current = [w]
        else:
            current.append(w)
    if current:
        lines.append(" ".join(current))
    return lines


def balanced_wrap(text: str, font: ImageFont.FreeTypeFont, max_w: int,
                  max_lines: int | None = None) -> list[str]:
    """Wrap to N lines minimising the variance of line widths.

    Falls back to greedy if it can't fit in `max_lines`.
    """
    words = text.split()
    if not words:
        return []

    greedy = greedy_wrap(text, font, max_w)
    if not greedy:
        return []
    target_lines = len(greedy) if max_lines is None else min(len(greedy), max_lines)
    if target_lines <= 1 or len(words) <= target_lines:
        return greedy

    # Try every split position; pick the one that minimises max line width.
    best: list[str] | None = None
    best_score = float("inf")

    def fits(lines: list[str]) -> bool:
        return all(_measure(font, ln) <= max_w for ln in lines)

    def score(lines: list[str]) -> float:
        widths = [_measure(font, ln) for ln in lines]
        return max(widths) * 1.2 + (max(widths) - min(widths))

    # Bruteforce only if word count is small enough; cheap on real headlines.
    n = len(words)
    if n <= 20 and target_lines <= 5:
        from itertools import combinations
        for cuts in combinations(range(1, n), target_lines - 1):
            chunks = [words[i:j] for i, j in zip((0,) + cuts, cuts + (n,))]
            lines = [" ".join(c) for c in chunks]
            if fits(lines) and score(lines) < best_score:
                best_score = score(lines)
                best = lines

    return best or greedy


def fit_font(font_path: str, text: str, max_w: int, *,
             max_size: int, min_size: int = 28, max_lines: int = 3,
             step: int = 4) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    """Binary-ish search for the largest font that fits text into max_w."""
    size = max_size
    chosen_font = ImageFont.truetype(font_path, size)
    chosen_lines = balanced_wrap(text, chosen_font, max_w, max_lines=max_lines)
    while size > min_size:
        font = ImageFont.truetype(font_path, size)
        lines = balanced_wrap(text, font, max_w, max_lines=max_lines)
        if len(lines) <= max_lines and all(_measure(font, ln) <= max_w for ln in lines):
            chosen_font, chosen_lines = font, lines
            break
        size -= step
        chosen_font, chosen_lines = font, lines
    return chosen_font, chosen_lines

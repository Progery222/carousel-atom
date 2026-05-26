"""Unit tests for the bait→reveal headline splitter in the seamless
design. The function is pure (no Pillow / no IO) so we can test it
without spinning up the whole design.

Run:  cd backend && pytest -q tests/test_seamless_split.py
"""
from __future__ import annotations

from designs.seamless import _split_headline_for_bait


def test_preposition_split_at():
    bait, reveal = _split_headline_for_bait(
        "LEWIS HAMILTON TAKES SWIPE AT F1 CHAMPION JACQUES VILLENEUVE AT CANADIAN GP"
    )
    # Split should land on one of the AT prepositions in the middle band.
    assert bait.endswith("…")
    assert "JACQUES VILLENEUVE" in reveal or "F1 CHAMPION" in reveal
    # Bait shouldn't be longer than reveal — keep the tease short.
    assert len(bait.split()) <= len(reveal.split()) + 2


def test_preposition_split_after():
    bait, reveal = _split_headline_for_bait(
        "BRAVES SEEM POISED TO COAST INTO THE PLAYOFFS AS MLB FIRST TEAM TO 30 WINS"
    )
    # 'AS' / 'INTO' / 'TO' are in the break list — split should be at
    # one of them in the middle band.
    assert bait.endswith("…")
    assert reveal  # non-empty


def test_short_headline_not_split():
    # ≤ 5 words: no split, both slides repeat the headline.
    bait, reveal = _split_headline_for_bait("VERSTAPPEN WINS BAHRAIN GRAND PRIX")
    assert reveal == ""
    assert "…" not in bait


def test_fallback_midpoint_avoids_orphan_lead_word():
    # No preposition in middle 30-70% → midpoint fallback. The reveal
    # half should NOT open with a leading function word like THE / OF.
    bait, reveal = _split_headline_for_bait(
        "JOHN STONES SCORES THE WINNER AGAINST CHELSEA IN CUP FINAL"
    )
    first_word = reveal.split()[0].upper().rstrip(",.;:")
    assert first_word not in {"THE", "A", "AN", "OF", "TO"}, (
        f"reveal opens with orphan function word: {reveal!r}"
    )


def test_reveal_not_empty_for_long_headline():
    bait, reveal = _split_headline_for_bait(
        "MANCHESTER CITY ANNOUNCES NEW SIGNING FOR THE UPCOMING SEASON FROM ATLETICO"
    )
    assert reveal.strip()
    assert bait.endswith("…")

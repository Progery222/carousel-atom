"""Tests for the punchy headline rewriter and accent-phrase picker.

These mirror the kind of transformations you can see on @f1newsflash:
strip SEO trailing clauses, shorten "Formula 1" → "F1", contractions,
and pick the punchy 1-2 final words for red highlighting.
"""
from core.text import accent_phrase, punchy


def test_drops_after_clause():
    out = punchy(
        "Verstappen seriously considering retiring from F1 at the end of "
        "2026 after Red Bull tensions"
    )
    assert "Red Bull tensions" not in out
    assert out.lower().endswith("end of 2026")


def test_shortens_formula_one():
    assert "F1" in punchy("Formula 1 chiefs to overhaul rules in 2027")
    assert "Formula 1" not in punchy("Formula 1 chiefs to overhaul rules")


def test_contractions():
    assert "doesn't" in punchy("F1 does not need Max Verstappen")
    assert "won't" in punchy("McLaren will not chase Verstappen this year")


def test_strips_leading_breaking():
    assert not punchy("BREAKING: Verstappen wins").lower().startswith("breaking")
    assert not punchy("REPORT: Hamilton signs deal").lower().startswith("report")


def test_caps_max_words():
    long = "Toto Wolff says everyone can stop complaining about Mercedes performance now"
    short = punchy(long, max_words=8)
    assert len(short.split()) <= 9  # 8 words + the trailing ellipsis token


def test_idempotent():
    s = "Verstappen seriously considering retiring from F1"
    assert punchy(punchy(s)) == punchy(s)


# ── accent_phrase ──────────────────────────────────────────────────────────


def test_accent_uses_trigger_after_modal():
    # @f1newsflash highlights "RETIRING" here, not "END OF 2026".
    accent = accent_phrase(
        "VERSTAPPEN SERIOUSLY CONSIDERING RETIRING FROM F1 AT THE END OF 2026"
    )
    assert "RETIRING" in accent
    assert "2026" not in accent


def test_accent_picks_to_verb_object():
    accent = accent_phrase("MCLAREN COULD USE LAMBIASE MOVE TO SIGN VERSTAPPEN")
    assert "SIGN" in accent and "VERSTAPPEN" in accent


def test_accent_picks_negation_pair():
    accent = accent_phrase("F1 DOESN'T NEED MAX VERSTAPPEN")
    assert "NEED" in accent
    # The negation itself stays white in our render to keep things
    # legible — only "NEED" matters as the action.


def test_accent_skips_stopwords():
    accent = accent_phrase("V8 ENGINES SET TO RETURN TO F1")
    assert "TO" not in accent
    assert "RETURN" in accent


def test_accent_short_title_keeps_one_white():
    accent = accent_phrase("DRIVER DIES")
    # 2-word title shouldn't have BOTH highlighted.
    assert len(accent) == 1


def test_accent_empty_safe():
    assert accent_phrase("") == set()

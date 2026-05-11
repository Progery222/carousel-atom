"""Tests for headline cleanup + trending-term extraction."""
from core.text import clean_headline, extract_trending_terms, hashtagify


def test_strips_publisher_tail():
    assert clean_headline("Verstappen wins Bahrain GP - ESPN") == "Verstappen wins Bahrain GP"
    assert clean_headline("Latest news | Formula 1®") == "Latest news"


def test_collapses_punctuation():
    assert clean_headline("Wow!!!") == "Wow!"
    assert clean_headline("Lewis says...") == "Lewis says…"


def test_idempotent():
    s = "Verstappen wins Bahrain GP"
    assert clean_headline(clean_headline(s)) == s


def test_extracts_recurring_proper_nouns():
    titles = [
        "Lewis Hamilton signs new deal at Mercedes",
        "Mercedes confirm Lewis Hamilton extension",
        "Hamilton on Mercedes future",
    ]
    terms = extract_trending_terms(titles, top_k=3, min_count=2)
    # bigram should appear first
    assert any("Hamilton" in t for t in terms)


def test_hashtagify_strips_punct():
    assert hashtagify("Lewis Hamilton") == "#lewishamilton"
    assert hashtagify("Verstappen!") == "#verstappen"

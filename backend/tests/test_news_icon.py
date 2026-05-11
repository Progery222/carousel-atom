"""Tests for the news_icon classifier — picks the corner badge symbol
based on article wording (mirrors the @f1newsflash icon system)."""
import time

from core.parsers.base import Article
from core.quality import news_icon


def make(title: str, *, description: str = "") -> Article:
    return Article(
        title=title,
        url="https://x/" + title[:20],
        source="ESPN",
        image_url="https://x/y.jpg",
        description=description,
        published_ts=int(time.time()) - 3600,
    )


def test_severe_returns_alert():
    assert news_icon(make("Driver dies after qualifying crash")) == "!"


def test_quoted_returns_quote_glyph():
    assert news_icon(make("Wolff says everyone can stop complaining")) == '"'


def test_negation_returns_cross():
    assert news_icon(make("F1 doesn't need Max Verstappen")) == "X"


def test_rumour_returns_question_mark():
    assert news_icon(make("McLaren could sign Verstappen for 2027")) == "?"
    assert news_icon(make("Ferrari expected to bring upgrade to Monaco")) == "?"


def test_default_is_exclamation():
    assert news_icon(make("Verstappen wins Bahrain Grand Prix")) == "!"

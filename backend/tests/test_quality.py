"""Unit tests for the quality gate / scoring / severity helpers.

Run:  cd backend && pytest -q
"""
from __future__ import annotations

import time

from core.parsers.base import Article
from core.quality import (
    is_news_content,
    passes_filters,
    score_article,
    severity_of,
)


def make(title: str, *, image_url: str = "https://x/y.jpg",
         description: str = "A reasonably detailed description for the article.",
         published_ts: int | None = None,
         source: str = "ESPN") -> Article:
    return Article(
        title=title,
        url="https://example.com/" + title.lower().replace(" ", "-"),
        source=source,
        image_url=image_url,
        description=description,
        published_ts=published_ts or int(time.time()) - 3600,
    )


# ── is_news_content ─────────────────────────────────────────────────────────


def test_quiz_is_dropped():
    ok, reason = is_news_content(make("Quiz: can you name every NBA MVP?"))
    assert not ok
    assert "non-news" in reason


def test_listicle_fluff_dropped():
    ok, reason = is_news_content(make("5 SHOCKING moments from last weekend"))
    assert not ok
    assert "listicle" in reason


def test_real_news_passes():
    ok, _ = is_news_content(make("Verstappen wins Bahrain Grand Prix after late charge"))
    assert ok


# Multi-event preview / teaser patterns that escaped the original regex
# and ended up on Sports Digest slides as ambiguous "predictions" headlines.
def test_game_by_game_predictions_dropped():
    ok, reason = is_news_content(
        make("Raiders game-by-game predictions after 2026 NFL Schedule release")
    )
    assert not ok
    assert "teaser" in reason


def test_schedule_release_dropped():
    ok, reason = is_news_content(
        make("'Thursday Night Football' schedule release: who plays Thanksgiving night")
    )
    assert not ok
    assert "teaser" in reason


def test_ranking_all_dropped():
    ok, reason = is_news_content(
        make("Ranking all 15 TNF matchups from worst to best for the 2026 season")
    )
    assert not ok
    # Either ranking_all in non-news, or worst-to-best in teaser — both work.
    assert "non-news" in reason or "teaser" in reason


def test_watch_live_as_dropped():
    ok, reason = is_news_content(
        make("Nurburgring 24 Hours Day 2: Watch live as Verstappen takes on Top Qualifying")
    )
    assert not ok
    assert "non-news" in reason


def test_bold_predictions_dropped():
    ok, reason = is_news_content(
        make("5 bold predictions for the NFL playoffs that nobody saw coming")
    )
    assert not ok
    assert "teaser" in reason


def test_mock_draft_dropped():
    ok, reason = is_news_content(
        make("2026 NFL mock draft 4.0: surprises in the first round")
    )
    assert not ok
    assert "teaser" in reason


def test_takeaways_recap_still_passes():
    # Real news: post-game recap with the score. Should NOT be filtered.
    ok, _ = is_news_content(
        make("Takeaways from the Ducks' 5-1 Loss to the Golden Knights, Vegas wins Series 4-2")
    )
    assert ok


def test_shopping_listicle_dropped():
    ok, reason = is_news_content(
        make("12 Best Leather Sandals for Men 2026, According to GQ Editors")
    )
    assert not ok
    assert "teaser" in reason


def test_every_player_listicle_dropped():
    ok, reason = is_news_content(
        make("World Cup 2026 squads: Every player at this summer's tournament")
    )
    assert not ok
    assert "teaser" in reason


def test_qualifying_result_still_passes():
    # Real news: qualifying placement is a discrete event result.
    ok, _ = is_news_content(
        make("Where Max Verstappen qualified for his Nurburgring 24 Hours debut")
    )
    assert ok


def test_video_url_dropped():
    art = make("Highlights from the latest game")
    art.url = "https://espn.com/video/highlights"
    ok, reason = is_news_content(art)
    assert not ok
    assert "URL" in reason


# ── passes_filters ──────────────────────────────────────────────────────────


def test_short_title_dropped():
    ok, reason = passes_filters(make("Too short"))
    assert not ok
    assert "short" in reason


def test_no_image_dropped():
    ok, reason = passes_filters(make("Verstappen takes pole at Imola GP", image_url=""))
    assert not ok
    assert "image" in reason


def test_stale_dropped():
    art = make("Verstappen takes pole at Imola GP",
               published_ts=int(time.time()) - 200 * 3600)
    ok, reason = passes_filters(art)
    assert not ok
    assert "stale" in reason


def test_blocklisted_word_dropped():
    art = make("Sponsored content from XYZ")
    ok, reason = passes_filters(art, blocklist=["sponsored"])
    assert not ok
    assert "block" in reason


# ── severity ────────────────────────────────────────────────────────────────


def test_severity_flags_tragedy():
    assert severity_of(make("Driver dies after qualifying crash")) == "severe"


def test_severity_normal_story():
    assert severity_of(make("Verstappen wins Bahrain Grand Prix")) == "normal"


# ── scoring ─────────────────────────────────────────────────────────────────


def test_score_prefers_image_and_description():
    a = make("Verstappen wins Bahrain GP after late charge", image_url="https://x.jpg",
             description="Verstappen overtook Hamilton on lap 53 after a safety car.")
    b = make("Verstappen wins Bahrain GP after late charge", image_url="",
             description="")
    assert score_article(a) > score_article(b)


def test_severe_articles_rank_lower_than_upbeat():
    bad = make("Driver dies after qualifying crash at Spa")
    good = make("Verstappen wins Bahrain Grand Prix after late charge")
    assert score_article(good) > score_article(bad)

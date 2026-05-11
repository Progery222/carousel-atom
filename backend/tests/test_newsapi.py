"""NewsAPI parser — exercised against a mocked HTTP response."""
from unittest.mock import patch

from core.parsers import newsapi


class _Resp:
    status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return {
            "status": "ok",
            "totalResults": 2,
            "articles": [
                {
                    "title": "Verstappen wins Bahrain GP",
                    "url": "https://example.com/1",
                    "urlToImage": "https://example.com/1.jpg",
                    "description": "An exciting win to open the season.",
                    "publishedAt": "2026-04-29T15:30:00Z",
                },
                {
                    "title": "[Removed]",
                    "url": "https://example.com/2",
                },
                {
                    "title": "Hamilton signs new deal",
                    "url": "https://example.com/3",
                    "urlToImage": "",
                    "description": "Multi-year extension at Mercedes.",
                    "publishedAt": "2026-04-28T11:00:00Z",
                },
            ],
        }


def test_returns_empty_without_api_key(monkeypatch):
    monkeypatch.delenv("NEWSAPI_KEY", raising=False)
    assert newsapi.fetch_newsapi("f1", "NewsAPI") == []


def test_parses_articles_and_drops_removed(monkeypatch):
    monkeypatch.setenv("NEWSAPI_KEY", "k")
    with patch("core.parsers.newsapi.http_client.get", return_value=_Resp()):
        out = newsapi.fetch_newsapi("formula 1", "NewsAPI · F1")
    assert len(out) == 2  # "[Removed]" was dropped
    assert out[0].title == "Verstappen wins Bahrain GP"
    assert out[0].image_url == "https://example.com/1.jpg"
    assert out[0].published_ts is not None


def test_handles_provider_error(monkeypatch):
    monkeypatch.setenv("NEWSAPI_KEY", "k")
    with patch("core.parsers.newsapi.http_client.get", side_effect=RuntimeError("boom")):
        out = newsapi.fetch_newsapi("f1", "NewsAPI")
    assert out == []

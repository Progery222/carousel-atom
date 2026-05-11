"""Tests for the image-search fallback chain.

We mock the shared HTTP layer so the suite never hits the network. The
goal is to verify (a) entity extraction picks the right candidate query,
(b) Wikimedia results parse correctly, (c) Pexels/Unsplash adapters skip
when no API key is set, (d) the public `find_replacement_image` keeps
trying sources until one returns a hit.
"""
from __future__ import annotations

from unittest.mock import patch

from core.image_search import (
    find_replacement_image,
    search_pexels,
    search_unsplash,
    search_wikimedia,
)
from core.text import extract_entities


# ── extract_entities ────────────────────────────────────────────────────────


def test_entities_prefer_multiword_proper_nouns():
    out = extract_entities("Lionel Messi signs new Inter Miami contract")
    assert "Lionel Messi" in out
    assert "Inter Miami" in out
    # Bigrams should appear before standalone names in the output order.
    assert out.index("Lionel Messi") < out.index("Messi") if "Messi" in out else True


def test_entities_skip_function_words():
    out = extract_entities("McLaren could sign Verstappen")
    assert "could" not in [t.lower() for t in out]
    assert "McLaren" in out
    assert "Verstappen" in out


def test_entities_handles_no_proper_nouns():
    # Headline with no obvious entities — extractor returns empty list.
    out = extract_entities("the best sticker collectors face their biggest year")
    assert out == []


# ── HTTP-stub helpers ───────────────────────────────────────────────────────


class _Resp:
    def __init__(self, payload, status: int = 200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


# ── Wikimedia ───────────────────────────────────────────────────────────────


def test_wikimedia_returns_thumb_url(monkeypatch):
    search_payload = {
        "query": {"search": [{"title": "File:Lionel Messi 2018.jpg"}]}
    }
    info_payload = {
        "query": {
            "pages": {
                "1": {
                    "imageinfo": [{
                        "thumburl": "https://upload.wikimedia.org/.../1600px-Messi.jpg",
                        "thumbwidth": 1600,
                    }]
                }
            }
        }
    }
    responses = iter([_Resp(search_payload), _Resp(info_payload)])
    with patch("core.image_search.http_client.get",
               side_effect=lambda *a, **kw: next(responses)):
        url = search_wikimedia("Lionel Messi")
    assert url == "https://upload.wikimedia.org/.../1600px-Messi.jpg"


def test_wikimedia_no_results():
    payload = {"query": {"search": []}}
    with patch("core.image_search.http_client.get", return_value=_Resp(payload)):
        assert search_wikimedia("zzzzzzzzzzzzzz no such thing") is None


def test_wikimedia_skips_low_res():
    """If the thumbnail is below MIN_RESULT_WIDTH, we drop it."""
    search_payload = {
        "query": {"search": [{"title": "File:Tiny.jpg"}]}
    }
    info_payload = {
        "query": {"pages": {"1": {"imageinfo": [
            {"thumburl": "https://x/tiny.jpg", "thumbwidth": 200}
        ]}}}
    }
    responses = iter([_Resp(search_payload), _Resp(info_payload)])
    with patch("core.image_search.http_client.get",
               side_effect=lambda *a, **kw: next(responses)):
        url = search_wikimedia("Tiny")
    assert url is None


# ── Pexels & Unsplash ───────────────────────────────────────────────────────


def test_pexels_disabled_without_key(monkeypatch):
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    assert search_pexels("anything") is None


def test_pexels_picks_large(monkeypatch):
    monkeypatch.setenv("PEXELS_API_KEY", "k")
    payload = {"photos": [{
        "src": {
            "large2x": "https://pexels/large2x.jpg",
            "large": "https://pexels/large.jpg",
        }
    }]}
    with patch("core.image_search.http_client.get", return_value=_Resp(payload)):
        url = search_pexels("panini stickers")
    assert url == "https://pexels/large2x.jpg"


def test_unsplash_disabled_without_key(monkeypatch):
    monkeypatch.delenv("UNSPLASH_ACCESS_KEY", raising=False)
    assert search_unsplash("anything") is None


# ── Public chain ────────────────────────────────────────────────────────────


def test_find_replacement_walks_chain(monkeypatch):
    """First source returns nothing, second returns a URL — chain should
    fall through and return the second one."""
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    monkeypatch.delenv("UNSPLASH_ACCESS_KEY", raising=False)

    # Stub Wikimedia: empty search → returns None.
    empty = {"query": {"search": []}}

    def fake_wiki(query):
        return None

    def fake_pex(query):
        return "https://pexels/found.jpg"

    url = find_replacement_image(
        "Panini Football Sticker Collectors face £1,000 outlay",
        sources=(fake_wiki, fake_pex),
    )
    assert url == "https://pexels/found.jpg"


def test_find_replacement_returns_none_when_all_fail():
    url = find_replacement_image(
        "Panini Football Sticker Collectors",
        sources=(lambda q: None, lambda q: None),
    )
    assert url is None

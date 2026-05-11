"""LLM rewriter — exercised with a mocked HTTP layer.

The real provider call is isolated in `core.llm.caption_rewriter`. We
swap out `requests.post` so the test runs offline.
"""
from __future__ import annotations

import os
from unittest.mock import patch

import core.llm as llm


class _Resp:
    status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return {
            "choices": [
                {"message": {"content": "A SHARPER VERSION OF THE CAPTION"}}
            ]
        }


def test_rewriter_disabled_without_api_key(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    assert llm.caption_rewriter() is None


def test_rewriter_calls_provider(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    rewriter = llm.caption_rewriter()
    assert rewriter is not None

    with patch("core.llm.http_client.post", return_value=_Resp()) as m:
        out = rewriter("Original caption")
        assert "SHARPER" in out
        assert m.called
        # Make sure auth header was built correctly.
        kwargs = m.call_args.kwargs
        assert kwargs["headers"]["Authorization"] == "Bearer test-key"
        assert kwargs["json"]["model"]


def test_rewriter_falls_back_on_error(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    rewriter = llm.caption_rewriter()
    with patch("core.llm.http_client.post", side_effect=RuntimeError("boom")):
        out = rewriter("My original")
        assert out == "My original"  # original returned on error

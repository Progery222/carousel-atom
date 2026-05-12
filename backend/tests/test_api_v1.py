"""Tests for the public /api/v1 router: auth, rate limiting, ZIP export.

The pipeline itself is mocked — we only verify the API surface here.
Render/preview pipeline behavior is covered by other test files.
"""
from __future__ import annotations

import io
import zipfile

import pytest


@pytest.fixture
def client_with_keys(monkeypatch, tmp_path):
    """Spin up a TestClient with two configured API keys.

    Each fixture invocation reloads the auth module from env so tests
    don't leak keys into each other.
    """
    monkeypatch.setenv("CAROUSEL_API_KEYS", "internal:goodkey,partner:secondkey")
    # Point OUTPUT_DIR at a temp location so the ZIP export test can
    # create fake run directories without touching real data.
    monkeypatch.setenv("CAROUSEL_OUTPUT_DIR", str(tmp_path))

    from api import auth
    auth.reload_keys()

    from fastapi.testclient import TestClient
    from api.server import app
    return TestClient(app)


@pytest.fixture
def client_no_keys(monkeypatch):
    monkeypatch.setenv("CAROUSEL_API_KEYS", "")
    from api import auth
    auth.reload_keys()
    from fastapi.testclient import TestClient
    from api.server import app
    return TestClient(app)


def test_503_when_no_keys_configured(client_no_keys):
    r = client_no_keys.get("/api/v1/topics")
    assert r.status_code == 503
    body = r.json()
    assert body["error"]["code"] == "service_unavailable"


def test_401_without_header(client_with_keys):
    r = client_with_keys.get("/api/v1/topics")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthorized"


def test_401_with_wrong_key(client_with_keys):
    r = client_with_keys.get("/api/v1/topics", headers={"X-API-Key": "nope"})
    assert r.status_code == 401


def test_200_with_valid_key(client_with_keys):
    r = client_with_keys.get("/api/v1/topics", headers={"X-API-Key": "goodkey"})
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_second_key_also_works(client_with_keys):
    r = client_with_keys.get("/api/v1/topics", headers={"X-API-Key": "secondkey"})
    assert r.status_code == 200


def test_health_is_public(client_with_keys):
    r = client_with_keys.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_openapi_schema_only_lists_v1_paths(client_with_keys):
    r = client_with_keys.get("/api/v1/openapi.json")
    assert r.status_code == 200
    paths = r.json()["paths"]
    assert all(p.startswith("/api/v1/") for p in paths), paths


def test_request_id_header_round_trip(client_with_keys):
    r = client_with_keys.get(
        "/api/v1/topics",
        headers={"X-API-Key": "goodkey", "X-Request-ID": "trace-abc"},
    )
    assert r.headers.get("X-Request-ID") == "trace-abc"


def test_zip_export_404_for_unknown_run(client_with_keys):
    r = client_with_keys.get(
        "/api/v1/export/missing-run-id.zip",
        headers={"X-API-Key": "goodkey"},
    )
    assert r.status_code == 404


def test_zip_export_streams_run_dir(client_with_keys, monkeypatch):
    from api import v1
    from core import pipeline

    # Build a fake run directory: <OUTPUT_DIR>/<topic>/<run_id>/slide_*.png
    fake_run = pipeline.OUTPUT_DIR / "f1" / "f1_newsflash_1234_abcdef"
    fake_run.mkdir(parents=True, exist_ok=True)
    (fake_run / "slide_0.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 64)
    (fake_run / "slide_1.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 64)
    (fake_run / "caption.txt").write_text("hello world")

    # The resolver needs `f1` to be a known topic — patch the lookup.
    monkeypatch.setattr(v1, "list_topics", lambda: ["f1"])

    r = client_with_keys.get(
        f"/api/v1/export/{fake_run.name}.zip",
        headers={"X-API-Key": "goodkey"},
    )
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    names = set(zf.namelist())
    assert "slide_0.png" in names
    assert "slide_1.png" in names
    assert "caption.txt" in names
    assert "metadata.json" in names


def test_render_calls_impl_with_base(client_with_keys, monkeypatch):
    """The render handler should pass an absolute URL base to the impl
    so slide URLs in the response are absolute, not root-relative."""
    captured: dict = {}

    def fake_render_impl(req, *, base=""):
        captured["base"] = base
        captured["topic"] = req.topic
        from api.schemas import RenderOut
        return RenderOut(
            status="ok", run_id="x", topic=req.topic, design=req.design,
            caption="c", articles=[], slides=[],
        )

    import api.server as server
    monkeypatch.setattr(server, "render_impl", fake_render_impl)

    r = client_with_keys.post(
        "/api/v1/render",
        headers={"X-API-Key": "goodkey"},
        json={"topic": "f1", "design": "newsflash"},
    )
    assert r.status_code == 200, r.text
    assert captured["topic"] == "f1"
    assert captured["base"].startswith("http"), captured


def test_unified_error_envelope_for_v1(client_with_keys):
    """An unknown topic should come back wrapped in the v1 error envelope."""
    r = client_with_keys.get(
        "/api/v1/preview/articles?topic=__definitely_not_a_topic__",
        headers={"X-API-Key": "goodkey"},
    )
    assert r.status_code == 404
    body = r.json()
    assert "error" in body
    assert body["error"]["code"] == "not_found"
    assert "request_id" in body["error"]


def test_rate_limit_trips_on_dynamic_path(monkeypatch):
    """Regression: the heavy limit must trip for repeated calls to the
    same endpoint even when the URL path differs by a dynamic segment
    (e.g. /export/{run_id}.zip). This guards against slowapi's default
    `key_style="url"` which buckets by resolved path and would never
    trip on /export/x1.zip vs /export/x2.zip."""
    monkeypatch.setenv("CAROUSEL_API_KEYS", "ratekey")
    monkeypatch.setenv("CAROUSEL_API_RATE_LIMIT", "2/minute")
    # Force re-import so the new env values stick to module-level singletons.
    import importlib
    import sys
    for mod in ["api.rate_limit", "api.auth", "api.v1", "api.server"]:
        sys.modules.pop(mod, None)
    from api import rate_limit  # noqa: F401
    importlib.import_module("api.auth").reload_keys()
    from fastapi.testclient import TestClient
    from api.server import app
    client = TestClient(app)

    codes = []
    for i in range(4):
        r = client.get(f"/api/v1/export/run_{i}.zip", headers={"X-API-Key": "ratekey"})
        codes.append(r.status_code)
    # First two return 404 (run doesn't exist), then we exceed 2/min.
    assert codes[:2] == [404, 404], codes
    assert 429 in codes[2:], codes


def test_internal_route_keeps_legacy_error_shape(client_with_keys):
    """The studio frontend parses {detail: ...} — don't break that on
    internal (non-v1) routes."""
    r = client_with_keys.get("/preview/articles?topic=__nope__")
    assert r.status_code == 404
    body = r.json()
    assert "detail" in body
    assert "error" not in body

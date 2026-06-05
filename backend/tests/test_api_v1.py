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

    from api import auth
    auth.reload_keys()

    from fastapi.testclient import TestClient
    from api.server import app

    # Point OUTPUT_DIR at a temp dir across every module that reads it, so the
    # ZIP / run tests build fake run directories without touching real data.
    # (OUTPUT_DIR is a hardcoded constant in core.pipeline — the old
    # CAROUSEL_OUTPUT_DIR env var was never read, so tests used to write into
    # the real backend/data/output. Patching the module bindings fixes that.)
    import core.pipeline as pipeline
    import api.server as server
    import api.v1 as v1
    for mod in (pipeline, server, v1):
        monkeypatch.setattr(mod, "OUTPUT_DIR", tmp_path)

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


# ── run.json persistence + run-details endpoint ─────────────────────────────


@pytest.fixture
def api_client(monkeypatch):
    """Isolated TestClient with generous rate limits and a fresh job store.

    Re-imports the api modules so leaked module-level limits from other tests
    (notably the rate-limit regression test, which bakes a 2/minute cap into
    a re-imported `api.rate_limit`) can't bleed into the render/job tests.
    """
    monkeypatch.setenv("CAROUSEL_API_KEYS", "internal:goodkey,partner:secondkey")
    monkeypatch.setenv("CAROUSEL_API_RATE_LIMIT", "1000/minute")
    monkeypatch.setenv("CAROUSEL_API_RATE_LIMIT_LIGHT", "1000/minute")
    import importlib
    import sys
    for mod in ["api.rate_limit", "api.auth", "api.jobs", "api.v1", "api.server"]:
        sys.modules.pop(mod, None)
    importlib.import_module("api.auth").reload_keys()
    from fastapi.testclient import TestClient
    from api.server import app
    return TestClient(app)


def _install_fake_pipeline(monkeypatch, tmp_path, *, status="ok",
                           topic="f1", design="newsflash"):
    """Point OUTPUT_DIR at tmp_path across the modules that read it, and
    replace `run_once` with a network-free fake that writes a real slide
    PNG so URL building / ZIP / run-details work end to end."""
    import core.pipeline as pipeline
    import api.server as server
    import api.v1 as v1
    monkeypatch.setattr(pipeline, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(server, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(v1, "OUTPUT_DIR", tmp_path)

    def _fake_run_once(topic_slug, design_slug="newsflash", **kw):
        run_id = f"{topic_slug}_{design_slug}_1700000000_abcd12"
        if status != "ok":
            return {"status": status, "run_id": run_id,
                    "diagnostics": {"raw": 3, "fresh": 0, "drop_reasons": {"seen": 3}}}
        out_dir = tmp_path / topic_slug / run_id
        out_dir.mkdir(parents=True, exist_ok=True)
        slide = out_dir / "slide_0.png"
        slide.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 64)
        return {
            "status": "ok", "run_id": run_id, "topic": topic_slug,
            "design": design_slug, "slide_paths": [str(slide)],
            "caption": "Verstappen wins Monaco 🏎",
            "articles": [{"title": "Headline A", "url": "https://x/a",
                          "source": "BBC", "image_url": "", "description": "d"}],
            "output_dir": str(out_dir), "diagnostics": {"raw": 5},
        }

    monkeypatch.setattr(server, "run_once", _fake_run_once)
    return topic, design


def test_run_json_persisted_and_run_details_round_trip(api_client, monkeypatch, tmp_path):
    topic, design = _install_fake_pipeline(monkeypatch, tmp_path)
    r = api_client.post("/api/v1/render", headers={"X-API-Key": "goodkey"},
                        json={"topic": topic, "design": design})
    assert r.status_code == 200, r.text
    body = r.json()
    run_id = body["run_id"]

    # run.json was written next to the slides.
    meta_file = tmp_path / topic / run_id / "run.json"
    assert meta_file.exists()

    # GET /runs/{run_id} reconstructs caption + articles + slides from disk.
    r2 = api_client.get(f"/api/v1/runs/{run_id}", headers={"X-API-Key": "goodkey"})
    assert r2.status_code == 200, r2.text
    got = r2.json()
    assert got["caption"] == "Verstappen wins Monaco 🏎"
    assert got["articles"][0]["title"] == "Headline A"
    assert got["slides"][0]["url"].endswith(f"/output/{topic}/{run_id}/slide_0.png")


def test_run_details_404_for_unknown_run(api_client, monkeypatch, tmp_path):
    _install_fake_pipeline(monkeypatch, tmp_path)
    monkeypatch.setattr("api.v1.list_topics", lambda: ["f1"])
    r = api_client.get("/api/v1/runs/f1_newsflash_0_zzz",
                       headers={"X-API-Key": "goodkey"})
    assert r.status_code == 404


# ── async jobs ──────────────────────────────────────────────────────────────


def _poll_job(client, job_id, *, timeout=8.0):
    import time
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        r = client.get(f"/api/v1/jobs/{job_id}", headers={"X-API-Key": "goodkey"})
        assert r.status_code == 200, r.text
        body = r.json()
        if body["status"] in ("succeeded", "failed"):
            return body
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not finish in {timeout}s")


def test_async_job_happy_path(api_client, monkeypatch, tmp_path):
    topic, design = _install_fake_pipeline(monkeypatch, tmp_path)

    r = api_client.post("/api/v1/jobs", headers={"X-API-Key": "goodkey"},
                        json={"kind": "render", "topic": topic, "design": design})
    assert r.status_code == 202, r.text
    sub = r.json()
    assert sub["status"] in ("queued", "running")
    assert sub["status_url"].endswith(f"/api/v1/jobs/{sub['job_id']}")

    final = _poll_job(api_client, sub["job_id"])
    assert final["status"] == "succeeded", final
    assert final["result"]["caption"] == "Verstappen wins Monaco 🏎"
    assert final["result"]["slides"][0]["url"].endswith("slide_0.png")


def test_async_job_failure_maps_to_failed(api_client, monkeypatch, tmp_path):
    topic, design = _install_fake_pipeline(monkeypatch, tmp_path, status="no_usable")

    r = api_client.post("/api/v1/jobs", headers={"X-API-Key": "goodkey"},
                        json={"kind": "render", "topic": topic, "design": design})
    assert r.status_code == 202, r.text
    final = _poll_job(api_client, r.json()["job_id"])
    assert final["status"] == "failed", final
    assert final["error"]["code"] == "no_usable"
    assert final["result"] is None


def test_jobs_unknown_topic_fails_fast_with_404(api_client, monkeypatch, tmp_path):
    _install_fake_pipeline(monkeypatch, tmp_path)
    r = api_client.post("/api/v1/jobs", headers={"X-API-Key": "goodkey"},
                        json={"kind": "render", "topic": "zzz_unknown",
                              "design": "newsflash"})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


# ── webhook SSRF guard ──────────────────────────────────────────────────────


def test_webhook_ssrf_rejects_internal_targets(monkeypatch):
    from api.jobs import is_safe_webhook_url
    monkeypatch.delenv("CAROUSEL_ALLOW_LOCAL", raising=False)
    monkeypatch.delenv("CAROUSEL_WEBHOOK_ALLOW_HOSTS", raising=False)
    assert is_safe_webhook_url("https://127.0.0.1/hook") is False
    assert is_safe_webhook_url("https://10.0.0.1/hook") is False
    assert is_safe_webhook_url("https://100.64.1.1/hook") is False  # tailnet/CGNAT
    assert is_safe_webhook_url("http://example.com/hook") is False   # https required


def test_webhook_allowlist_and_local_optin(monkeypatch):
    from api.jobs import is_safe_webhook_url
    monkeypatch.setenv("CAROUSEL_WEBHOOK_ALLOW_HOSTS", "receiver.internal")
    assert is_safe_webhook_url("https://receiver.internal/hook") is True
    monkeypatch.setenv("CAROUSEL_ALLOW_LOCAL", "1")
    assert is_safe_webhook_url("http://127.0.0.1:9000/hook") is True


def test_webhook_not_fired_for_rejected_url(monkeypatch):
    """A blocked webhook_url must never reach the HTTP client."""
    import api.jobs as jobs
    monkeypatch.delenv("CAROUSEL_ALLOW_LOCAL", raising=False)
    monkeypatch.delenv("CAROUSEL_WEBHOOK_ALLOW_HOSTS", raising=False)
    called = {"n": 0}

    class _FakeSession:
        def post(self, *a, **k):
            called["n"] += 1
            raise AssertionError("should not be called")

    monkeypatch.setattr(jobs.http, "session", lambda: _FakeSession())
    job = jobs.Job(id="j1", kind="render", status="succeeded",
                   webhook_url="https://127.0.0.1/hook", finished_at=1.0)
    jobs._deliver_webhook(job)
    assert called["n"] == 0


def test_webhook_signed_delivery(monkeypatch):
    import hashlib
    import hmac
    import api.jobs as jobs
    monkeypatch.setenv("CAROUSEL_WEBHOOK_ALLOW_HOSTS", "receiver.internal")
    monkeypatch.setenv("CAROUSEL_WEBHOOK_SECRET", "s3cret")
    captured = {}

    class _Resp:
        status_code = 200

    class _FakeSession:
        def post(self, url, *, data, headers, timeout, allow_redirects):
            captured["url"] = url
            captured["data"] = data
            captured["headers"] = headers
            return _Resp()

    monkeypatch.setattr(jobs.http, "session", lambda: _FakeSession())
    result = {"status": "ok", "run_id": "f1_newsflash_1_a", "caption": "Win 🏎",
              "slides": [{"index": 0, "url": "https://x/slide_0.png"}], "articles": []}
    job = jobs.Job(id="j2", kind="render", status="succeeded", result=result,
                   webhook_url="https://receiver.internal/hook", finished_at=2.0)
    jobs._deliver_webhook(job)
    assert captured["url"] == "https://receiver.internal/hook"
    expected = "sha256=" + hmac.new(b"s3cret", captured["data"], hashlib.sha256).hexdigest()
    assert captured["headers"]["X-Carousel-Signature"] == expected
    # The payload body carries the terminal state + result (emoji preserved).
    import json
    payload = json.loads(captured["data"])
    assert payload["status"] == "succeeded"
    assert payload["error"] is None
    assert payload["result"]["caption"] == "Win 🏎"
    assert payload["finished_at"] == 2


# ── validation envelopes ────────────────────────────────────────────────────


def test_v1_validation_error_uses_envelope(api_client):
    """A bad slug (uppercase / punctuation) trips schema validation → 422 in
    the unified v1 envelope."""
    r = api_client.post("/api/v1/render", headers={"X-API-Key": "goodkey"},
                        json={"topic": "BAD SLUG!", "design": "newsflash"})
    assert r.status_code == 422
    body = r.json()
    assert body["error"]["code"] == "unprocessable_entity"
    assert "request_id" in body["error"]


def test_internal_validation_error_keeps_legacy_shape(api_client):
    """Internal /render keeps FastAPI's {detail: [...]} 422 shape so the
    studio frontend is unaffected."""
    r = api_client.post("/render", json={"topic": "BAD SLUG!", "design": "x"})
    assert r.status_code == 422
    body = r.json()
    assert "detail" in body
    assert "error" not in body


def test_render_unknown_topic_is_404_not_409(api_client, monkeypatch, tmp_path):
    _install_fake_pipeline(monkeypatch, tmp_path)
    r = api_client.post("/api/v1/render", headers={"X-API-Key": "goodkey"},
                        json={"topic": "zzz_unknown", "design": "newsflash"})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


# ── path traversal / security ───────────────────────────────────────────────


def test_run_endpoints_reject_topic_path_traversal(api_client, monkeypatch, tmp_path):
    """`?topic=../../..` must never escape OUTPUT_DIR — the slug pattern rejects
    it with 422 before any filesystem access (regression for the traversal
    found in review)."""
    _install_fake_pipeline(monkeypatch, tmp_path)
    r = api_client.get("/api/v1/runs/leak?topic=../../..",
                       headers={"X-API-Key": "goodkey"})
    assert r.status_code == 422, r.text
    r2 = api_client.get("/api/v1/export/leak.zip?topic=../../..",
                        headers={"X-API-Key": "goodkey"})
    assert r2.status_code == 422, r2.text


# ── async job kinds + discriminated union ───────────────────────────────────


def test_async_job_render_edit_kind(api_client, monkeypatch, tmp_path):
    topic, design = _install_fake_pipeline(monkeypatch, tmp_path)
    r = api_client.post(
        "/api/v1/jobs", headers={"X-API-Key": "goodkey"},
        json={"kind": "render_edit", "topic": topic, "design": design,
              "articles": [{"title": "A", "url": "https://x/a", "source": "S"}]},
    )
    assert r.status_code == 202, r.text
    final = _poll_job(api_client, r.json()["job_id"])
    assert final["status"] == "succeeded", final
    assert final["result"]["run_id"]


def test_async_job_unknown_kind_is_422(api_client):
    r = api_client.post("/api/v1/jobs", headers={"X-API-Key": "goodkey"},
                        json={"kind": "bogus", "topic": "f1", "design": "newsflash"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "unprocessable_entity"


# ── run-details degradation + job store TTL ─────────────────────────────────


def test_run_details_degrades_without_run_json(api_client, monkeypatch, tmp_path):
    """A run dir with slides but no run.json (legacy run) still returns 200,
    degrading to slides-only (caption='' , articles=[])."""
    import core.pipeline as pipeline
    import api.server as server
    import api.v1 as v1
    for mod in (pipeline, server, v1):
        monkeypatch.setattr(mod, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr("api.v1.list_topics", lambda: ["f1"])
    run_id = "f1_newsflash_1700000000_zzz"
    d = tmp_path / "f1" / run_id
    d.mkdir(parents=True)
    (d / "slide_0.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 64)
    r = api_client.get(f"/api/v1/runs/{run_id}", headers={"X-API-Key": "goodkey"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["caption"] == ""
    assert body["articles"] == []
    assert body["topic"] == "f1"
    assert len(body["slides"]) == 1


def test_job_store_ttl_eviction():
    """A finished job past its TTL is evicted on the next submit()."""
    from api.jobs import Job, JobStore

    store = JobStore(max_workers=1, ttl=0.0)
    try:
        old = Job(id="old", kind="render", status="succeeded",
                  created_at=1.0, finished_at=1.0)
        with store._lock:
            store._jobs["old"] = old

        class _Out:
            def model_dump(self):
                return {}

        store.submit("render", lambda: _Out(), base="")
        assert store.get("old") is None
    finally:
        store.shutdown()

"""Tests for the public /api/v1 cross-service standard surface.

Covers: the {success,data,meta} envelope, X-API-Key auth (env bootstrap + DB
keys), scopes (read/write/admin), the unified error codes, cursor pagination,
the system endpoints, and API-key management. The render pipeline is mocked —
pipeline behavior is covered by other test files.
"""
from __future__ import annotations

import importlib
import io
import sys
import time
import zipfile

import pytest


def _build_client(monkeypatch, tmp_path, *, keys="boot:adminkey",
                  limit="1000/minute", raise_server_exceptions=True):
    """Fresh, isolated TestClient: temp SQLite DB, generous limits, env reload.
    Re-imports the api modules so module-level limits/keys can't bleed between
    tests."""
    monkeypatch.setenv("CAROUSEL_API_KEYS", keys)
    monkeypatch.setenv("CAROUSEL_API_RATE_LIMIT", limit)
    monkeypatch.setenv("CAROUSEL_API_RATE_LIMIT_LIGHT", limit)
    monkeypatch.delenv("CAROUSEL_ALLOW_LOCAL", raising=False)
    monkeypatch.delenv("CAROUSEL_WEBHOOK_ALLOW_HOSTS", raising=False)
    for m in ["api.rate_limit", "api.auth", "api.jobs", "api.responses",
              "api.v1", "api.server"]:
        sys.modules.pop(m, None)
    import core.dedup as dedup
    monkeypatch.setattr(dedup, "DB_PATH", tmp_path / "test.db")
    dedup.init_db()
    import core.api_keys as api_keys
    api_keys.init_db()
    importlib.import_module("api.auth").reload_keys()
    from fastapi.testclient import TestClient
    from api.server import app
    return TestClient(app, raise_server_exceptions=raise_server_exceptions)


@pytest.fixture
def client(monkeypatch, tmp_path):
    return _build_client(monkeypatch, tmp_path)


ADMIN = {"X-API-Key": "adminkey"}


def _make_key(client, name="reader", scopes=("read",)) -> str:
    r = client.post("/api/v1/api-keys", headers=ADMIN,
                    json={"name": name, "scopes": list(scopes)})
    assert r.status_code == 201, r.text
    return r.json()["data"]["key"]


def _install_fake_pipeline(monkeypatch, tmp_path, *, status="ok",
                           topic="f1", design="newsflash", run_suffix="abcd12"):
    """Patch OUTPUT_DIR everywhere + replace run_once with a network-free fake
    that writes a real slide PNG so URL building / ZIP / run.json work."""
    import core.pipeline as pipeline
    import api.server as server
    import api.v1 as v1
    out = tmp_path / "output"
    for mod in (pipeline, server, v1):
        monkeypatch.setattr(mod, "OUTPUT_DIR", out)

    def _fake_run_once(topic_slug, design_slug="newsflash", **kw):
        run_id = f"{topic_slug}_{design_slug}_1700000000_{run_suffix}"
        if status != "ok":
            return {"status": status, "run_id": run_id,
                    "diagnostics": {"raw": 3, "fresh": 0, "drop_reasons": {"seen": 3}}}
        d = out / topic_slug / run_id
        d.mkdir(parents=True, exist_ok=True)
        (d / "slide_0.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 64)
        return {
            "status": "ok", "run_id": run_id, "topic": topic_slug,
            "design": design_slug, "slide_paths": [str(d / "slide_0.png")],
            "caption": "Verstappen wins Monaco 🏎",
            "articles": [{"title": "Headline A", "url": "https://x/a",
                          "source": "BBC", "image_url": "", "description": "d"}],
            "output_dir": str(d), "diagnostics": {"raw": 5},
        }

    monkeypatch.setattr(server, "run_once", _fake_run_once)
    return topic, design


# ── envelope + system endpoints ─────────────────────────────────────────────


def test_health_is_public_enveloped(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["data"]["status"] == "ok"
    assert body["data"]["version"]
    assert "request_id" in body["meta"]


def test_meta_describes_contract(client):
    body = client.get("/api/v1/meta").json()
    data = body["data"]
    assert data["service"] == "carousel-studio"
    assert data["api_version"] == "v1"
    assert set(data["scopes"]) == {"read", "write", "admin"}
    assert "render" in data["capabilities"]["actions"]
    assert data["auth"]["name"] == "X-API-Key"
    assert data["pagination"]["style"] == "cursor"


def test_openapi_security_and_v1_only(client):
    schema = client.get("/api/v1/openapi.json").json()
    assert all(p.startswith("/api/v1") for p in schema["paths"])
    assert "ApiKeyAuth" in schema["components"]["securitySchemes"]


def test_request_id_round_trip(client):
    r = client.get("/api/v1/health", headers={"X-Request-ID": "trace-xyz"})
    assert r.headers.get("X-Request-ID") == "trace-xyz"
    assert r.json()["meta"]["request_id"] == "trace-xyz"


# ── auth ────────────────────────────────────────────────────────────────────


def test_missing_key_is_401_envelope(client):
    r = client.get("/api/v1/topics")
    assert r.status_code == 401
    body = r.json()
    assert body["success"] is False
    assert body["error"]["code"] == "unauthorized"
    assert "request_id" in body["meta"]


def test_wrong_key_is_401_generic(client):
    r = client.get("/api/v1/topics", headers={"X-API-Key": "nope"})
    assert r.status_code == 401
    # Same generic message as missing/no-keys — no provisioning disclosure.
    assert r.json()["error"]["message"] == "invalid or missing API key"


def test_env_admin_key_works(client):
    r = client.get("/api/v1/topics", headers=ADMIN)
    assert r.status_code == 200
    assert isinstance(r.json()["data"], list)


def test_auth_verify_reports_identity(client):
    body = client.get("/api/v1/auth/verify", headers=ADMIN).json()["data"]
    assert body["name"] == "boot"
    assert body["scopes"] == ["admin"]


# ── API key management ──────────────────────────────────────────────────────


def test_create_key_shows_raw_once_and_hashes(client):
    r = client.post("/api/v1/api-keys", headers=ADMIN,
                    json={"name": "partner", "scopes": ["read", "write"]})
    assert r.status_code == 201
    data = r.json()["data"]
    raw = data["key"]
    assert raw.startswith("csk_")
    assert data["key_prefix"] == raw[:12]
    assert sorted(data["scopes"]) == ["read", "write"]
    # The raw secret never appears again in list/get.
    listed = client.get("/api/v1/api-keys", headers=ADMIN).json()["data"]
    assert all("key" not in k for k in listed)
    got = client.get(f"/api/v1/api-keys/{data['key_id']}", headers=ADMIN).json()["data"]
    assert "key" not in got
    # And the new key authenticates.
    assert client.get("/api/v1/auth/verify", headers={"X-API-Key": raw}).status_code == 200


def test_create_key_requires_admin(client):
    reader = _make_key(client, scopes=["read"])
    r = client.post("/api/v1/api-keys", headers={"X-API-Key": reader},
                    json={"name": "x", "scopes": ["read"]})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "forbidden"


def test_create_key_unknown_scope_422(client):
    r = client.post("/api/v1/api-keys", headers=ADMIN,
                    json={"name": "x", "scopes": ["superuser"]})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"


def test_revoked_key_is_rejected(client):
    raw = _make_key(client, scopes=["read"])
    key_id = client.get("/api/v1/api-keys", headers=ADMIN).json()["data"][0]["key_id"]
    assert client.delete(f"/api/v1/api-keys/{key_id}", headers=ADMIN).status_code == 200
    assert client.get("/api/v1/topics", headers={"X-API-Key": raw}).status_code == 401


# ── scopes ──────────────────────────────────────────────────────────────────


def test_read_scope_cannot_write(client, monkeypatch, tmp_path):
    _install_fake_pipeline(monkeypatch, tmp_path)
    reader = _make_key(client, scopes=["read"])
    r = client.post("/api/v1/actions/render", headers={"X-API-Key": reader},
                    json={"topic": "f1", "design": "newsflash"})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "forbidden"
    # read can still read
    assert client.get("/api/v1/topics", headers={"X-API-Key": reader}).status_code == 200


def test_write_scope_can_render(client, monkeypatch, tmp_path):
    _install_fake_pipeline(monkeypatch, tmp_path)
    writer = _make_key(client, scopes=["write"])
    r = client.post("/api/v1/actions/render", headers={"X-API-Key": writer},
                    json={"topic": "f1", "design": "newsflash"})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["run_id"]


# ── actions + runs ──────────────────────────────────────────────────────────


def test_action_render_persists_and_runs_roundtrip(client, monkeypatch, tmp_path):
    _install_fake_pipeline(monkeypatch, tmp_path)
    r = client.post("/api/v1/actions/render", headers=ADMIN,
                    json={"topic": "f1", "design": "newsflash"})
    assert r.status_code == 200, r.text
    run = r.json()["data"]
    run_id = run["run_id"]
    assert run["caption"] == "Verstappen wins Monaco 🏎"

    # run.json sidecar written
    assert (tmp_path / "output" / "f1" / run_id / "run.json").exists()
    # GET /runs/{id} reconstructs from disk
    got = client.get(f"/api/v1/runs/{run_id}", headers=ADMIN).json()["data"]
    assert got["articles"][0]["title"] == "Headline A"
    assert got["slides"][0]["url"].endswith(f"/output/f1/{run_id}/slide_0.png")
    # GET /runs lists it (indexed via dedup.record_run)
    listed = client.get("/api/v1/runs", headers=ADMIN).json()["data"]
    assert any(it["run_id"] == run_id for it in listed["items"])


def test_runs_cursor_pagination(client, monkeypatch, tmp_path):
    # Three runs at increasing created_at via the dedup index directly.
    import core.dedup as dedup
    for i in range(3):
        dedup.record_run(run_id=f"f1_newsflash_170000000{i}_r{i}", topic="f1",
                         design="newsflash", created_at=1700000000 + i,
                         slide_count=5, caption=f"c{i}")
    p1 = client.get("/api/v1/runs?limit=2", headers=ADMIN).json()["data"]
    assert len(p1["items"]) == 2
    assert p1["next_cursor"]
    p2 = client.get(f"/api/v1/runs?limit=2&cursor={p1['next_cursor']}",
                    headers=ADMIN).json()["data"]
    assert len(p2["items"]) == 1
    assert p2["next_cursor"] is None
    seen = [it["run_id"] for it in p1["items"] + p2["items"]]
    assert len(set(seen)) == 3  # no dup / skip across the boundary


def test_bad_cursor_is_422(client):
    r = client.get("/api/v1/runs?cursor=@@notbase64@@", headers=ADMIN)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"


def test_delete_run(client, monkeypatch, tmp_path):
    _install_fake_pipeline(monkeypatch, tmp_path)
    run_id = client.post("/api/v1/actions/render", headers=ADMIN,
                         json={"topic": "f1", "design": "newsflash"}).json()["data"]["run_id"]
    assert client.delete(f"/api/v1/runs/{run_id}", headers=ADMIN).status_code == 200
    assert client.get(f"/api/v1/runs/{run_id}", headers=ADMIN).status_code == 404


def test_export_zip_and_traversal_guard(client, monkeypatch, tmp_path):
    _install_fake_pipeline(monkeypatch, tmp_path)
    run_id = client.post("/api/v1/actions/render", headers=ADMIN,
                         json={"topic": "f1", "design": "newsflash"}).json()["data"]["run_id"]
    z = client.get(f"/api/v1/runs/{run_id}/export", headers=ADMIN)
    assert z.status_code == 200
    assert z.headers["content-type"] == "application/zip"
    names = set(zipfile.ZipFile(io.BytesIO(z.content)).namelist())
    assert {"slide_0.png", "caption.txt", "metadata.json"} <= names
    # path traversal via topic query -> 422 (slug pattern), never escapes
    assert client.get("/api/v1/runs/x/export?topic=../../..",
                      headers=ADMIN).status_code == 422
    assert client.get("/api/v1/runs/x?topic=../../..", headers=ADMIN).status_code == 422


# ── async jobs ──────────────────────────────────────────────────────────────


def _poll_job(client, job_id, *, timeout=8.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get(f"/api/v1/jobs/{job_id}", headers=ADMIN).json()["data"]
        if body["status"] in ("succeeded", "failed"):
            return body
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} never finished")


def test_async_job_lifecycle_and_listing(client, monkeypatch, tmp_path):
    _install_fake_pipeline(monkeypatch, tmp_path)
    r = client.post("/api/v1/jobs", headers=ADMIN,
                    json={"kind": "render", "topic": "f1", "design": "newsflash"})
    assert r.status_code == 202, r.text
    sub = r.json()["data"]
    assert sub["status"] in ("queued", "running")
    final = _poll_job(client, sub["job_id"])
    assert final["status"] == "succeeded"
    assert final["result"]["caption"] == "Verstappen wins Monaco 🏎"
    # listed under GET /jobs (paginated)
    page = client.get("/api/v1/jobs?limit=10", headers=ADMIN).json()["data"]
    assert any(j["job_id"] == sub["job_id"] for j in page["items"])
    assert "next_cursor" in page


def test_async_job_failure_maps_to_failed(client, monkeypatch, tmp_path):
    _install_fake_pipeline(monkeypatch, tmp_path, status="no_usable")
    r = client.post("/api/v1/jobs", headers=ADMIN,
                    json={"kind": "render", "topic": "f1", "design": "newsflash"})
    final = _poll_job(client, r.json()["data"]["job_id"])
    assert final["status"] == "failed"
    assert final["error"]["code"] == "no_usable"


def test_jobs_unknown_kind_422(client):
    r = client.post("/api/v1/jobs", headers=ADMIN,
                    json={"kind": "bogus", "topic": "f1", "design": "newsflash"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"


# ── errors ──────────────────────────────────────────────────────────────────


def test_unknown_topic_is_404(client, monkeypatch, tmp_path):
    _install_fake_pipeline(monkeypatch, tmp_path)
    r = client.post("/api/v1/actions/render", headers=ADMIN,
                    json={"topic": "zzz_unknown", "design": "newsflash"})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


def test_validation_error_envelope(client):
    r = client.post("/api/v1/actions/render", headers=ADMIN,
                    json={"topic": "BAD SLUG!", "design": "newsflash"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"
    assert "details" in r.json()["error"]


def test_internal_routes_keep_legacy_shape(client):
    # Studio internal routes are untouched: {detail}, no envelope.
    r = client.get("/preview/articles?topic=__nope__")
    assert r.status_code == 404
    assert "detail" in r.json() and "error" not in r.json()
    bad = client.post("/render", json={"topic": "BAD SLUG!", "design": "x"})
    assert bad.status_code == 422
    assert "detail" in bad.json() and "error" not in bad.json()


def test_internal_error_returns_envelope(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path, raise_server_exceptions=False)
    import api.server as server

    def _boom():
        raise RuntimeError("kaboom: /secret/path leak")

    monkeypatch.setattr(server, "list_topics_impl", _boom)
    r = client.get("/api/v1/topics", headers=ADMIN)
    assert r.status_code == 500
    body = r.json()
    assert body["success"] is False
    assert body["error"]["code"] == "internal_error"
    assert body["error"]["message"] == "internal error"  # no leaked internals


def test_rate_limit_429_envelope(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path, limit="2/minute")
    codes = [client.get("/api/v1/topics", headers=ADMIN).status_code for _ in range(4)]
    assert 429 in codes
    last = client.get("/api/v1/topics", headers=ADMIN)
    if last.status_code == 429:
        assert last.json()["error"]["code"] == "rate_limited"
        assert "Retry-After" in last.headers


# ── webhook SSRF guard (unchanged jobs internals) ───────────────────────────


def test_webhook_ssrf_rejects_internal(monkeypatch, tmp_path):
    _build_client(monkeypatch, tmp_path)  # ensures fresh api.jobs import
    from api.jobs import is_safe_webhook_url
    assert is_safe_webhook_url("https://127.0.0.1/h") is False
    assert is_safe_webhook_url("https://10.0.0.1/h") is False
    assert is_safe_webhook_url("https://100.64.1.1/h") is False
    assert is_safe_webhook_url("http://example.com/h") is False


def test_webhook_signed_payload(monkeypatch, tmp_path):
    _build_client(monkeypatch, tmp_path)
    import hashlib
    import hmac
    import json as _json
    import api.jobs as jobs
    monkeypatch.setenv("CAROUSEL_WEBHOOK_ALLOW_HOSTS", "receiver.internal")
    monkeypatch.setenv("CAROUSEL_WEBHOOK_SECRET", "s3cret")
    captured = {}

    class _Resp:
        status_code = 200

    class _Sess:
        def post(self, url, *, data, headers, timeout, allow_redirects):
            captured.update(url=url, data=data, headers=headers)
            return _Resp()

    monkeypatch.setattr(jobs.http, "session", lambda: _Sess())
    job = jobs.Job(id="j1", kind="render", status="succeeded",
                   result={"run_id": "r", "caption": "Win 🏎"},
                   webhook_url="https://receiver.internal/h", finished_at=2.0)
    jobs._deliver_webhook(job)
    expected = "sha256=" + hmac.new(b"s3cret", captured["data"], hashlib.sha256).hexdigest()
    assert captured["headers"]["X-Carousel-Signature"] == expected
    payload = _json.loads(captured["data"])
    assert payload["status"] == "succeeded"
    assert payload["result"]["caption"] == "Win 🏎"

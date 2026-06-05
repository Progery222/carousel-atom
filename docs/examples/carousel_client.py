"""Minimal reference client for the Carousel Studio public API (/api/v1).

A thin, dependency-light wrapper (only `requests`) so a consuming service can
render carousels without hand-rolling HTTP. Copy it into your project and adapt.

    pip install requests

    from carousel_client import CarouselClient
    c = CarouselClient("https://your-app.example.com", "your-api-key")
    run = c.render_and_wait("f1", "newsflash")
    print(run["caption"])
    for slide in run["slides"]:
        print(slide["url"])

Run directly for a smoke test against a local instance:

    CAROUSEL_BASE=http://localhost:8000 CAROUSEL_KEY=k1 python carousel_client.py f1 newsflash
"""
from __future__ import annotations

import os
import time
from typing import Any, Optional

import requests


class CarouselError(RuntimeError):
    """Raised for a non-2xx API response. Carries the parsed error envelope."""

    def __init__(self, status: int, payload: Any):
        self.status = status
        self.payload = payload
        # New envelope: {success:false, error:{code,message,...}, meta:{...}}
        err = payload.get("error", payload) if isinstance(payload, dict) else payload
        super().__init__(f"HTTP {status}: {err}")


class CarouselClient:
    def __init__(self, base_url: str, api_key: str, *, timeout: float = 30.0):
        self.base = base_url.rstrip("/")
        self.timeout = timeout
        self._s = requests.Session()
        self._s.headers["X-API-Key"] = api_key

    # ── low-level ────────────────────────────────────────────────────────
    def _request(self, method: str, path: str, **kw) -> Any:
        kw.setdefault("timeout", self.timeout)
        r = self._s.request(method, f"{self.base}{path}", **kw)
        if r.status_code >= 400:
            try:
                payload = r.json()
            except ValueError:
                payload = r.text
            raise CarouselError(r.status_code, payload)
        resp = r.json() if r.content else None
        # Every JSON response is enveloped: {success, data, meta}.
        # Unwrap so callers always receive the inner payload.
        if isinstance(resp, dict) and "data" in resp:
            return resp["data"]
        return resp

    # ── discovery ────────────────────────────────────────────────────────
    def list_topics(self) -> list[dict]:
        return self._request("GET", "/api/v1/topics")

    def list_designs(self) -> list[dict]:
        return self._request("GET", "/api/v1/designs")

    def preview(self, topic: str, limit: int = 12) -> dict:
        return self._request("POST", "/api/v1/actions/preview",
                             json={"topic": topic, "limit": limit})

    # ── render (synchronous) ─────────────────────────────────────────────
    def render(self, topic: str, design: str, **opts) -> dict:
        """Blocking render. Use a long timeout — a run takes 10–40 s."""
        body = {"topic": topic, "design": design, **opts}
        return self._request("POST", "/api/v1/actions/render", json=body, timeout=90)

    # ── render (asynchronous) ────────────────────────────────────────────
    def submit_job(self, kind: str, *, webhook_url: Optional[str] = None,
                   **fields) -> dict:
        """Enqueue an async render. `kind` is render | render_edit | render_partial.
        Returns the 202 JobOut (envelope unwrapped) with a `job_id`."""
        body: dict[str, Any] = {"kind": kind, **fields}
        if webhook_url:
            body["webhook_url"] = webhook_url
        return self._request("POST", "/api/v1/jobs", json=body)

    def get_job(self, job_id: str) -> dict:
        return self._request("GET", f"/api/v1/jobs/{job_id}")

    def wait_for_job(self, job_id: str, *, interval: float = 3.0,
                     timeout: float = 180.0) -> dict:
        """Poll until the job reaches a terminal state. Returns the final
        JobOut (envelope unwrapped). Raises CarouselError if the render failed."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            job = self.get_job(job_id)
            if job["status"] == "succeeded":
                return job
            if job["status"] == "failed":
                raise CarouselError(409, {"error": job["error"]})
            time.sleep(interval)
        raise TimeoutError(f"job {job_id} did not finish within {timeout}s")

    def render_and_wait(self, topic: str, design: str, **opts) -> dict:
        """Async render + poll, returning the RenderOut (job result)."""
        job = self.submit_job("render", topic=topic, design=design, **opts)
        return self.wait_for_job(job["job_id"])["result"]

    # ── results ──────────────────────────────────────────────────────────
    def get_run(self, run_id: str, topic: Optional[str] = None) -> dict:
        params = {"topic": topic} if topic else None
        return self._request("GET", f"/api/v1/runs/{run_id}", params=params)

    def list_runs(self, *, limit: int = 20, cursor: Optional[str] = None) -> dict:
        """Fetch one page of runs. Returns {items, next_cursor}. Loop until
        next_cursor is None to page through all runs."""
        params: dict[str, Any] = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        return self._request("GET", "/api/v1/runs", params=params)

    def export_zip(self, run_id: str, dest: str, topic: Optional[str] = None) -> str:
        params = {"topic": topic} if topic else None
        r = self._s.get(f"{self.base}/api/v1/runs/{run_id}/export",
                        params=params, timeout=60)
        if r.status_code >= 400:
            try:
                payload = r.json()
            except ValueError:
                payload = r.text  # non-JSON body (e.g. a proxy/Funnel error page)
            raise CarouselError(r.status_code, payload)
        with open(dest, "wb") as f:
            f.write(r.content)
        return dest

    # ── admin ────────────────────────────────────────────────────────────
    def create_key(self, name: str, scopes: list[str]) -> dict:
        """Create a new scoped API key (admin scope required).
        The raw secret is returned once in the response as `key`."""
        return self._request("POST", "/api/v1/api-keys",
                             json={"name": name, "scopes": scopes})


if __name__ == "__main__":
    import sys

    base = os.environ.get("CAROUSEL_BASE", "http://localhost:8000")
    key = os.environ.get("CAROUSEL_KEY", "")
    topic = sys.argv[1] if len(sys.argv) > 1 else "f1"
    design = sys.argv[2] if len(sys.argv) > 2 else "newsflash"

    client = CarouselClient(base, key)
    print("topics:", [t["slug"] for t in client.list_topics()])
    print(f"rendering {topic}/{design} (async)...")
    run = client.render_and_wait(topic, design)
    print("run_id:", run["run_id"])
    print("caption:", run["caption"][:120], "...")
    for s in run["slides"]:
        print(" ", s["url"])

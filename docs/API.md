# Carousel Studio Public API

Versioned REST API for generating TikTok / Instagram news carousels from your
own service. The same pipeline that powers the studio frontend is exposed under
`/api/v1` with API-key auth, rate-limiting, async jobs and webhooks.

> **Interactive docs (on the running app):** `/api/v1/docs` (Swagger UI),
> `/api/v1/redoc` (ReDoc), `/api/v1/openapi.json` (OpenAPI 3.1 spec — import
> this into Postman / Insomnia or feed it to `openapi-generator`).
> `/api-docs` is the custom in-app reference.

- [Quickstart](#quickstart-5-minutes)
- [Authentication](#authentication)
- [Endpoints](#endpoints)
- [Rendering: sync vs async](#rendering-sync-vs-async)
- [Async jobs](#async-jobs)
- [Webhooks](#webhooks)
- [Fetching results](#fetching-results)
- [Errors](#errors)
- [Rate limits](#rate-limits)
- [Browsers, CORS & key safety](#browsers-cors--key-safety)
- [Operator guide](#operator-guide)

---

## Quickstart (5 minutes)

You need: the base URL of a running instance (e.g.
`https://carousel-atom.tailXXXX.ts.net`) and an API key from the operator.

```bash
BASE="https://your-app.example.com"
KEY="your-api-key"

# 1. What can I render?
curl -s -H "X-API-Key: $KEY" "$BASE/api/v1/topics"
curl -s -H "X-API-Key: $KEY" "$BASE/api/v1/designs"

# 2. Kick off an async render (returns immediately with a job_id)
JOB=$(curl -s -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"kind":"render","topic":"f1","design":"newsflash"}' \
  "$BASE/api/v1/jobs" | jq -r .job_id)

# 3. Poll until the job is done (queued → running → succeeded/failed)
curl -s -H "X-API-Key: $KEY" "$BASE/api/v1/jobs/$JOB" | jq

# 4. When status == "succeeded", the response carries result.run_id and
#    result.slides[].url. Re-fetch any time by run_id:
curl -s -H "X-API-Key: $KEY" "$BASE/api/v1/runs/<run_id>" | jq

# 5. Or download the whole run as a ZIP (slides + caption + metadata):
curl -s -H "X-API-Key: $KEY" "$BASE/api/v1/export/<run_id>.zip" -o run.zip
```

A ready-to-run Python client and curl/JS snippets live in
[`docs/examples/`](examples/).

---

## Authentication

Every `/api/v1/*` request (except `/api/v1/health`) must carry an `X-API-Key`
header. Keys are configured by the operator via `CAROUSEL_API_KEYS`
(comma-separated, optional `name:key` form for per-key logs + rate-limit
buckets):

```bash
# Server-side
export CAROUSEL_API_KEYS="internal:abc123,partner_acme:xyz789"
```

```bash
# Client-side
curl -H "X-API-Key: abc123" https://your-app.example.com/api/v1/topics
```

If `CAROUSEL_API_KEYS` is empty, every `/api/v1` call returns **503**. The
legacy non-prefixed routes used by the studio frontend are unaffected.

---

## Endpoints

| Method | Path | Tier | Description |
|---|---|---|---|
| GET  | `/api/v1/topics`                 | light | List configured topics |
| GET  | `/api/v1/designs`                | light | List available design templates |
| GET  | `/api/v1/preview/articles`       | light | Preview fresh candidates (no render) |
| POST | `/api/v1/render`                 | heavy | **Sync** full render (blocks 10–40 s) |
| POST | `/api/v1/render/edit`            | heavy | **Sync** re-render with supplied articles |
| POST | `/api/v1/render/partial`         | heavy | **Sync** per-slot re-roll |
| POST | `/api/v1/jobs`                   | heavy | **Async** render → `202` + `job_id` |
| GET  | `/api/v1/jobs/{job_id}`          | light | Async job status + result |
| GET  | `/api/v1/runs/{run_id}`          | light | Re-fetch a finished run (caption + slides) |
| GET  | `/api/v1/export/{run_id}.zip`    | heavy | Download a run as ZIP |
| GET  | `/api/v1/health`                 | none  | Liveness ping (no auth) |
| GET  | `/api/v1/docs` · `/redoc` · `/openapi.json` | none | Interactive docs / spec |

---

## Rendering: sync vs async

A render pulls fresh news, enriches + verifies images, renders slides and
builds a caption. It typically takes **10–40 s** (image fetching dominates).

- **Sync** (`POST /api/v1/render*`) holds the HTTP connection open for the
  whole run and returns the finished `RenderOut`. Simple, but a reverse proxy
  / Tailscale Funnel / browser may time the request out. Use a client timeout
  **≥ 60 s** and call it from a background worker.
- **Async** (`POST /api/v1/jobs`) returns in milliseconds with a `job_id`;
  you poll or receive a webhook. **Recommended for anything user-facing or
  behind a proxy.**

The three render kinds share one request body shape:

```jsonc
// kind = "render": pull fresh news and render
{ "topic": "f1", "design": "newsflash",
  "mark_seen": true, "cross_topic_dedup": false, "deliver": "" }

// kind = "render_edit": render exactly the articles you supply (no fetch)
{ "topic": "f1", "design": "newsflash",
  "articles": [ { "title": "...", "url": "...", "source": "...",
                  "image_url": "...", "description": "..." } ] }

// kind = "render_partial": lock some slots, re-roll the nulls
{ "topic": "f1", "design": "newsflash",
  "articles": [ { "title": "Locked", "url": "...", "source": "..." }, null, null ] }
```

`RenderOut` (returned by the sync endpoints, by `GET /runs/{run_id}`, and
nested under `result` in a finished job):

```json
{
  "status": "ok",
  "run_id": "f1_newsflash_1715000000_a1b2c3",
  "topic": "f1",
  "design": "newsflash",
  "caption": "F1 News · Verstappen wins Monaco...",
  "articles": [
    { "title": "...", "url": "...", "source": "...",
      "image_url": "...", "description": "..." }
  ],
  "slides": [
    { "index": 0, "url": "https://your-app.example.com/output/f1/.../slide_0.png" }
  ],
  "diagnostics": { "raw": 87, "fresh": 42, "after_enrich": 18,
                   "drop_reasons": { "seen": 23 } }
}
```

Slide URLs are absolute. The host comes from `PUBLIC_BASE_URL` (set this
behind a reverse proxy) or the request host.

**Validation** — `topic` / `design` must match `^[a-z0-9_]+$`; an unknown
topic/design returns **404** *before* any work starts (not a late 409).
Oversized bodies (title > 500, description > 4000, url > 2048 chars, or more
than 20 articles) return **422**.

---

## Async jobs

Submit a job, then poll `GET /api/v1/jobs/{job_id}`. Supply an optional
`webhook_url` to be called on completion instead of (or as well as) polling.

```bash
curl -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"kind":"render","topic":"f1","design":"newsflash",
       "webhook_url":"https://my-service.example.com/carousel/done"}' \
  "$BASE/api/v1/jobs"
```

`202 Accepted`:

```json
{
  "job_id": "9f1c2a...",
  "kind": "render",
  "status": "queued",
  "created_at": 1715000000,
  "status_url": "https://your-app.example.com/api/v1/jobs/9f1c2a..."
}
```

> The JSON examples here elide always-null/derived fields for brevity. The wire
> shape always includes the full `JobOut` (`started_at`, `finished_at`,
> `result`, `error` — `null` until set — and `status_url`).

**State machine** — poll the `status_url` (a 2–5 s interval is plenty; jobs
take tens of seconds):

```
queued ──▶ running ──▶ succeeded   (result: RenderOut)
                   └──▶ failed      (error: { code, message, details? })
```

A finished job:

```json
{
  "job_id": "9f1c2a...", "kind": "render", "status": "succeeded",
  "created_at": 1715000000, "started_at": 1715000001, "finished_at": 1715000034,
  "result": { "status": "ok", "run_id": "f1_newsflash_...", "slides": [ ... ], ... },
  "error": null
}
```

A failed job (e.g. the topic had no fresh stories today):

```json
{
  "job_id": "9f1c2a...", "status": "failed",
  "result": null,
  "error": { "code": "no_usable", "message": "render failed",
             "details": { "raw": 5, "fresh": 2, "drop_reasons": { "seen": 3 } } }
}
```

> **Durability — important.** The job store is **in-process and
> single-instance**: a `job_id` is ephemeral. It is evicted ~1 h after
> completion (`CAROUSEL_API_JOB_TTL`) and **dropped entirely on a
> restart/redeploy**. The durable handle is `run_id`: once a render
> succeeds, its slides + caption persist on disk and stay readable via
> `GET /api/v1/runs/{run_id}` even after the job is gone. Persist the
> `run_id` from the job result (or the webhook) and treat a `404` on a
> `job_id` as "poll the run instead." Submitting the same render twice is
> not deduplicated — each call renders again.

---

## Webhooks

If you pass `webhook_url`, the server POSTs a JSON body to it when the job
reaches a terminal state — **on both `succeeded` and `failed`**:

```json
{
  "job_id": "9f1c2a...",
  "kind": "render",
  "status": "succeeded",
  "result": { "...RenderOut, or null on failure..." },
  "error": null,
  "finished_at": 1715000034
}
```

**Verify the signature.** When `CAROUSEL_WEBHOOK_SECRET` is set, every
delivery carries `X-Carousel-Signature: sha256=<hex>` — an HMAC-SHA256 of the
**raw request body** keyed by the secret. Verify it before trusting the
payload:

```python
import hashlib, hmac

def verify(raw_body: bytes, header: str, secret: str) -> bool:
    expected = "sha256=" + hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header or "")
```

**Delivery semantics** — best-effort: 5 s timeout, redirects not followed, one
retry, then the attempt is dropped (the result still persists; fetch it by
`run_id`). Your receiver should be idempotent and return `2xx` quickly.

**SSRF rules** — `webhook_url` is treated as untrusted. It must be `https://`
and resolve to a **public** IP; URLs resolving to loopback, RFC1918, link-local
or the CGNAT/Tailscale `100.64.0.0/10` range are rejected before the POST. To
allow a self-hosted receiver on a private address, the operator adds its
hostname to `CAROUSEL_WEBHOOK_ALLOW_HOSTS`.

> This guard is **best-effort**: it validates the address the host resolves to
> at check time, but the HTTP client re-resolves at connect time, so a caller
> who controls authoritative DNS could in principle rebind to a private address
> (a blind, authenticated SSRF). Delivery already requires a valid API key; for
> untrusted callers, constrain egress at the network layer and pin receivers via
> `CAROUSEL_WEBHOOK_ALLOW_HOSTS`.

---

## Fetching results

Two ways to get the rendered slides after a render finishes:

**`GET /api/v1/runs/{run_id}`** — returns the full `RenderOut` (caption,
articles, absolute slide URLs), reconstructed from disk. Works across restarts
and after the job is evicted. Pass `?topic=...` if a slug containing
underscores can't be recovered from the run id.

**`GET /api/v1/export/{run_id}.zip`** — streams a ZIP of `slide_*.png` +
`caption.txt` + `metadata.json`. Topic is auto-detected from the run id; pass
`?topic=...` to disambiguate.

**Slide URL access model.** Slide PNGs are served from `/output/...` as
**public, unauthenticated** URLs. The `run_id` carries a random suffix, so a
URL acts as an unguessable capability token — but treat it as *shareable*, not
*secret forever*. Anything that must stay private should be delivered through
the auth'd ZIP export rather than by handing out `/output` links.

---

## Errors

Unified envelope for every `/api/v1` failure:

```json
{
  "error": {
    "code": "rate_limited",
    "message": "rate limit exceeded: 30 per 1 minute",
    "request_id": "ab12cd34ef56"
  }
}
```

Pipeline failures (409) and validation failures (422) add a `details` object
(diagnostics, or the list of invalid fields).

| HTTP | code                  | When |
|------|-----------------------|------|
| 400  | bad_request           | Malformed request |
| 401  | unauthorized          | Missing/invalid `X-API-Key` |
| 404  | not_found             | Unknown topic / design / run / job |
| 409  | conflict / no_articles / no_fresh / no_usable | Pipeline couldn't assemble a carousel (see `details`) |
| 422  | unprocessable_entity  | Request body failed validation (see `details`) |
| 429  | rate_limited          | Per-key limit exceeded (see `Retry-After`) |
| 503  | service_unavailable   | Public API disabled (no keys configured) |

> The internal studio routes (no `/api/v1` prefix) keep FastAPI's default
> `{ "detail": ... }` error shape — only `/api/v1` uses the envelope above.

---

## Rate limits

Per-key (per-IP if anonymous), in-memory, sliding 1-minute window. Two tiers:

- **Heavy** — 30 req/min default · `/render*`, `/jobs`, `/export/*.zip` ·
  override via `CAROUSEL_API_RATE_LIMIT`
- **Light** — 120 req/min default · `/topics`, `/designs`,
  `/preview/articles`, `/jobs/{id}`, `/runs/{id}` · override via
  `CAROUSEL_API_RATE_LIMIT_LIGHT`

Exceeded responses come back as **429** with a `Retry-After` header. Note that
async throughput is also bounded by `CAROUSEL_API_JOB_WORKERS` (default 2
concurrent renders) — enqueue is fast, but only N run at a time.

Every response includes an `X-Request-ID` header (12-char hex). Send your own
`X-Request-ID` to correlate client/server logs — it's echoed back and included
in error envelopes.

---

## Browsers, CORS & key safety

If you are building a **browser frontend** on top of this API: **do not put the
API key in browser JavaScript.** A key shipped to the browser is readable by
anyone and can be lifted and abused.

**Recommended — Backend-for-Frontend (BFF).** Your own server holds the
`X-API-Key` and proxies the calls; your browser app talks only to your server:

```
Browser ──(no key)──▶ Your backend ──(X-API-Key)──▶ Carousel /api/v1
```

This keeps the key server-side, lets you add your own auth/session, and avoids
CORS entirely (the browser never calls Carousel directly).

**`CAROUSEL_API_CORS`** defaults to `*` because the typical caller is
server-to-server (no browser, no `Origin`). Setting it to specific origins
only makes sense for a trusted same-origin admin tool — it is **not** a green
light for key-in-browser. For untrusted browsers, use the BFF above.

---

## Operator guide

Run an instance others can integrate against:

1. **Provision keys.** Set `CAROUSEL_API_KEYS` to one `name:key` per consumer
   (e.g. `partner_acme:$(openssl rand -hex 24)`). Per-key names show up in logs
   and rate-limit buckets. **Rotate** by adding the new key alongside the old,
   handing it over, then removing the old — both are valid during overlap.
   Removing a key (and restarting) revokes it immediately.
2. **Set `PUBLIC_BASE_URL`** to your public origin so slide URLs in responses
   are absolute and reachable (essential behind a reverse proxy / Funnel).
3. **Tune limits.** `CAROUSEL_API_RATE_LIMIT` / `_LIGHT` for request caps;
   `CAROUSEL_API_JOB_WORKERS` for async concurrency (keep small — each render
   already fans out ~8 image threads); `CAROUSEL_API_JOB_TTL` for how long
   finished jobs stay pollable.
4. **Webhooks.** Set `CAROUSEL_WEBHOOK_SECRET` so deliveries are signed. Add
   `CAROUSEL_WEBHOOK_ALLOW_HOSTS` only for trusted private receivers.
5. **CORS.** Leave `CAROUSEL_API_CORS=*` for server-to-server; otherwise list
   exact origins. Steer browser consumers to a BFF (above).
6. **Expose it.** This repo ships a Tailscale sidecar + Funnel config — see
   [DEPLOY.md](../DEPLOY.md) for the public-HTTPS setup.

> **Single-instance caveat.** Async jobs live in memory in one process. A
> redeploy (the CD pipeline restarts the container) drops every in-flight job.
> Consumers must tolerate a `job_id` going `404` and fall back to
> `GET /api/v1/runs/{run_id}`. Finished renders (slides + caption) are not
> lost — they persist on disk. Scaling to multiple replicas would need a
> shared job store (Redis); that's out of scope today.

---

## Under the hood

Every `/api/v1` route is a thin wrapper over `core.pipeline.run_once` /
`select_fresh_candidates` / `preview_articles` — the same pipeline that powers
the studio frontend. On a successful render the API layer writes a `run.json`
sidecar next to the slides (caption + article metadata the pipeline keeps only
in memory), which is what makes `GET /runs/{run_id}` and the ZIP caption work
after the original request is gone. No separate behavior, no separate quirks.

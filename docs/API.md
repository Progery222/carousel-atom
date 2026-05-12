# Carousel Studio Public API

Versioned REST API for generating TikTok / Instagram news carousels from
your own service. The same surface that the studio frontend uses
internally is also exposed under `/api/v1` with API-key auth and
rate-limiting.

> Live, interactive docs: **`/api-docs`** (in the running app) and
> **`/api/v1/docs`** (Swagger UI), **`/api/v1/redoc`** (ReDoc),
> **`/api/v1/openapi.json`** (OpenAPI 3.1 spec).

## Authentication

Every request to `/api/v1/*` (except `/health`) must carry an
`X-API-Key` header. Keys are configured by the operator via the
`CAROUSEL_API_KEYS` env var (comma-separated, optional `name:key` form):

```bash
# Server-side
export CAROUSEL_API_KEYS="internal:abc123,partner_acme:xyz789"
```

```bash
# Client-side
curl -H "X-API-Key: abc123" https://your-app.example.com/api/v1/topics
```

If `CAROUSEL_API_KEYS` is empty, every `/api/v1` call returns 503. The
legacy non-prefixed routes used by the studio frontend are unaffected by
this setting.

## Endpoints

| Method | Path | Tier | Description |
|---|---|---|---|
| GET  | `/api/v1/topics`                 | light | List configured topics |
| GET  | `/api/v1/designs`                | light | List available design templates |
| GET  | `/api/v1/preview/articles`       | light | Preview fresh article candidates (no render) |
| POST | `/api/v1/render`                 | heavy | Pull fresh news + render full carousel |
| POST | `/api/v1/render/edit`            | heavy | Re-render with user-supplied articles |
| POST | `/api/v1/render/partial`         | heavy | Per-slot re-roll (locked + null mix) |
| GET  | `/api/v1/export/{run_id}.zip`    | heavy | Download a rendered run as ZIP |
| GET  | `/api/v1/health`                 | none  | Liveness ping (no auth) |
| GET  | `/api/v1/docs`                   | none  | Swagger UI |
| GET  | `/api/v1/redoc`                  | none  | ReDoc |
| GET  | `/api/v1/openapi.json`           | none  | OpenAPI 3.1 spec |

### Request / response shapes

`POST /api/v1/render` request:

```json
{
  "topic": "f1",
  "design": "newsflash",
  "mark_seen": true,
  "cross_topic_dedup": false,
  "deliver": ""
}
```

`POST /api/v1/render` response (also for `/edit` and `/partial`):

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
    { "index": 0, "url": "https://api.example.com/output/f1/.../slide_0.png" }
  ],
  "diagnostics": {
    "raw": 87, "fresh": 42, "after_enrich": 18,
    "drop_reasons": { "seen": 23 }
  }
}
```

Slide URLs are absolute. Override the host the URL builder sees via the
`PUBLIC_BASE_URL` env var (handy behind a reverse proxy / on Railway).

`POST /api/v1/render/partial` body — items that are `null` get a fresh
story, non-null items are kept verbatim:

```json
{
  "topic": "f1",
  "design": "newsflash",
  "articles": [
    { "title": "Locked slide 1", "url": "...", "source": "...", "image_url": "..." },
    null,
    null
  ]
}
```

`GET /api/v1/export/{run_id}.zip` returns the run directory packaged as
a ZIP containing `slide_*.png`, `caption.txt` (when present), and a
`metadata.json` (`{run_id, topic, design, slide_count}`). The topic slug
is auto-detected from the run id; pass `?topic=...` if your slug
contains underscores and the heuristic can't disambiguate.

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

For pipeline failures (409), the original diagnostics dictionary is
preserved under `error.details`.

| HTTP | code                | When |
|------|---------------------|------|
| 400  | bad_request         | Validation failed |
| 401  | unauthorized        | Missing/invalid X-API-Key |
| 404  | not_found           | Topic or run not found |
| 409  | conflict / no_articles / no_fresh / no_usable | Pipeline couldn't assemble a carousel |
| 413  | payload_too_large   | Upload exceeds 12 MB |
| 429  | rate_limited        | Per-key limit exceeded (see Retry-After) |
| 503  | service_unavailable | Public API disabled (no keys configured) |

## Rate limits

Per-key, in-memory, sliding window. Two tiers:

- **Heavy** — 30 req/min default · `/render*`, `/export/*.zip` · override via `CAROUSEL_API_RATE_LIMIT`
- **Light** — 120 req/min default · `/topics`, `/designs`, `/preview/articles` · override via `CAROUSEL_API_RATE_LIMIT_LIGHT`

Exceeded responses come back as `429` with a `Retry-After` header.

## Request tracing

Every response includes an `X-Request-ID` header (12-char hex). Send
your own (`X-Request-ID` request header) to correlate client and server
logs — it is echoed back and included in error responses.

## Timing & async

`/api/v1/render` is **synchronous**. Typical latency is 10–30 seconds
(dominated by image fetching). Use a client timeout ≥60s and run it in
a background worker if you don't want to block a user-facing request
thread. The ZIP export is fast (<1s) and can be polled separately if
you cache `run_id`.

## CORS

Defaults to `*` because the typical caller is server-to-server (no
browser, no `Origin` header). Tighten via `CAROUSEL_API_CORS` (comma
list) if you call `/api/v1` from a browser app.

## Under the hood

Every `/api/v1` route is a thin wrapper over `core.pipeline.run_once` /
`select_fresh_candidates` / `preview_articles`. The same pipeline that
powers the studio frontend powers external API consumers — no separate
behavior, no separate quirks.

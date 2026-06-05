# Carousel Studio — External API (/api/v1)

A versioned REST API built to a **cross-service standard**: a central service
connects to every service the same way — by `X-API-Key`, with one response
envelope, one error-code set, cursor pagination, and scoped keys.

> **Interactive docs (on the running app):** `/api/v1/docs` (Swagger),
> `/api/v1/redoc` (ReDoc), `/api/v1/openapi.json` (OpenAPI 3.1 — import into a
> central service / Postman / `openapi-generator`). `/api-docs` is the in-app
> reference.

- [Base URL & headers](#base-url--headers)
- [Response envelope](#response-envelope)
- [Authentication & scopes](#authentication--scopes)
- [Error codes](#error-codes)
- [Pagination](#pagination)
- [System endpoints](#system-endpoints)
- [Resources & actions](#resources--actions)
- [Quickstart](#quickstart)
- [API key management](#api-key-management)
- [Async jobs & webhooks](#async-jobs--webhooks)
- [Operator guide](#operator-guide)

---

## Base URL & headers

```
Base URL:  https://your-app.example.com/api/v1
Auth:      X-API-Key: <key>
Body:      Content-Type: application/json
Trace:     X-Request-ID: <optional; echoed back>
```

## Response envelope

**Every** JSON response uses one shape. Success:

```json
{ "success": true, "data": <payload>, "meta": { "request_id": "ab12cd34" } }
```

Error:

```json
{ "success": false,
  "error": { "code": "not_found", "message": "...", "details": { } },
  "meta": { "request_id": "ab12cd34" } }
```

`data` is the resource/list; `details` is optional (validation fields, pipeline
diagnostics). Binary downloads (the run ZIP) are the only non-JSON responses.

## Authentication & scopes

Send `X-API-Key` on every request except the public system endpoints
(`/health`, `/meta`, `/openapi.json`). Two key kinds:

- **Bootstrap keys** — `CAROUSEL_API_KEYS` env (comma-separated, `name:key`
  form). Full **admin** scope. Used to mint scoped keys.
- **Scoped keys** — created via `POST /api/v1/api-keys`, stored **hashed**
  (only the hash is kept; the raw secret is shown once). Each carries scopes.

**Scopes** are hierarchical — `admin ⊃ write ⊃ read`:

| Scope | Grants |
|-------|--------|
| `read`  | discovery, runs, jobs, preview, auth/verify |
| `write` | everything `read` + render actions, create jobs, delete runs |
| `admin` | everything `write` + manage API keys |

A missing/unknown key returns a single generic **401** (no disclosure of
whether the instance is provisioned). Insufficient scope returns **403**.

## Error codes

Exactly seven codes across all services:

| HTTP | code | When |
|------|------|------|
| 401 | `unauthorized` | missing/invalid `X-API-Key` |
| 403 | `forbidden` | key lacks the required scope |
| 422 | `validation_error` | body/params failed validation (see `details`) |
| 404 | `not_found` | unknown topic/design/run/job/key |
| 409 | `conflict` | operation can't complete (e.g. no usable articles — see `details`) |
| 429 | `rate_limited` | per-key rate limit hit (see `Retry-After`) |
| 500 | `internal_error` | unexpected server error (generic; details in server logs) |

## Pagination

List endpoints (`GET /runs`, `GET /jobs`) use **cursor** pagination:

```
GET /api/v1/runs?limit=20&cursor=<opaque>
```

- `limit` — 1..100 (default 20).
- `cursor` — opaque token from the previous page; omit for the first page.
- Response `data`: `{ "items": [...], "next_cursor": "<token>" | null }`.

Loop until `next_cursor` is `null`. A malformed cursor → `422 validation_error`.

## System endpoints

| Method | Path | Auth | Returns (`data`) |
|--------|------|------|------------------|
| GET | `/api/v1/health` | none | `{ status, version }` |
| GET | `/api/v1/meta` | none | service name/version, capabilities, scopes, pagination, auth scheme |
| GET | `/api/v1/openapi.json` | none | OpenAPI 3.1 (enveloped responses + `ApiKeyAuth` scheme) |
| GET | `/api/v1/auth/verify` | any key | `{ key_id, name, scopes }` of the caller |

`GET /meta` is the machine-readable capability descriptor a central service can
read to learn what this service exposes.

## Resources & actions

**Resources** (CRUD-ish):

| Method | Path | Scope | Description |
|--------|------|-------|-------------|
| GET | `/api/v1/topics` · `/topics/{slug}` | read | configured topics |
| GET | `/api/v1/designs` · `/designs/{slug}` | read | design templates |
| GET | `/api/v1/runs` | read | rendered runs (cursor-paginated) |
| GET | `/api/v1/runs/{run_id}` | read | one run (caption, articles, slide URLs) |
| GET | `/api/v1/runs/{run_id}/export` | read | run as a ZIP (binary) |
| DELETE | `/api/v1/runs/{run_id}` | write | delete a run |
| GET | `/api/v1/jobs` · `/jobs/{job_id}` | read | async render jobs |
| POST | `/api/v1/jobs` | write | enqueue an async render → `202` |
| GET/POST/GET/DELETE | `/api/v1/api-keys[/{key_id}]` | admin | manage keys |

**Actions** (`POST /api/v1/actions/{name}`):

| Action | Scope | Body | Description |
|--------|-------|------|-------------|
| `render` | write | `{topic, design, mark_seen?, cross_topic_dedup?, deliver?}` | pull fresh news + render |
| `render-edit` | write | `{topic, design, articles:[...]}` | render supplied articles |
| `render-partial` | write | `{topic, design, articles:[... or null]}` | lock some slots, re-roll the rest |
| `preview` | read | `{topic, limit?}` | score candidates without rendering |

The render `data` (a `RenderOut`):

```json
{ "status": "ok", "run_id": "f1_newsflash_1715000000_a1b2c3",
  "topic": "f1", "design": "newsflash",
  "caption": "F1 News · ...",
  "articles": [ { "title": "...", "url": "...", "source": "...", "image_url": "...", "description": "..." } ],
  "slides": [ { "index": 0, "url": "https://your-app.example.com/output/f1/.../slide_0.png" } ],
  "diagnostics": { "raw": 87, "fresh": 42, "after_enrich": 18 } }
```

Slide URLs are absolute (`PUBLIC_BASE_URL` wins, else the request host).

## Quickstart

```bash
BASE="https://your-app.example.com/api/v1"; KEY="your-key"

# Discover
curl -s "$BASE/meta"                                   # no auth
curl -s -H "X-API-Key: $KEY" "$BASE/topics"

# Render (async — recommended behind a proxy)
JOB=$(curl -s -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
  -d '{"kind":"render","topic":"f1","design":"newsflash"}' \
  "$BASE/jobs" | jq -r .data.job_id)
curl -s -H "X-API-Key: $KEY" "$BASE/jobs/$JOB" | jq .data.status   # poll

# Or render synchronously
curl -s -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
  -d '{"topic":"f1","design":"newsflash"}' "$BASE/actions/render" | jq .data.run_id

# List runs (cursor-paginated)
curl -s -H "X-API-Key: $KEY" "$BASE/runs?limit=10" | jq '.data | {n: (.items|length), next: .next_cursor}'
```

Ready-to-run clients: [docs/examples/](examples/) (Python, curl, Node BFF,
browser, webhook receiver).

## API key management

Admin-only. The raw secret is returned **once** at creation; only its hash is
stored.

**Consuming an instance you don't run?** You don't create your own key — request a
scoped key from the operator of that instance. They mint it via the flow below and
hand you the `csk_...` secret (shown once); the rest of this section is for them.

```bash
# create a read+write key  → 201 Created
curl -s -H "X-API-Key: $ADMIN" -H 'Content-Type: application/json' \
  -d '{"name":"partner_acme","scopes":["read","write"]}' \
  "$BASE/api-keys" | jq .data        # -> { key_id, key: "csk_...", scopes, ... }

curl -s -H "X-API-Key: $ADMIN" "$BASE/api-keys"             # list (no raw secret)
curl -s -X DELETE -H "X-API-Key: $ADMIN" "$BASE/api-keys/<key_id>"   # revoke
```

`scopes` must be a subset of `read`/`write`/`admin` (else `422`).

## Async jobs & webhooks

`POST /api/v1/jobs` returns `202` + a `job_id`; poll `GET /api/v1/jobs/{job_id}`
(`queued → running → succeeded|failed`) or pass a `webhook_url`. The job store
is in-process/single-instance — `job_id` is ephemeral; the durable handle is
`run_id` (re-fetch via `GET /runs/{run_id}`). Webhooks are https-only, SSRF-
guarded, and HMAC-signed (`X-Carousel-Signature`, key `CAROUSEL_WEBHOOK_SECRET`).
See [docs/examples/webhook_receiver.py](examples/webhook_receiver.py).

## Operator guide

Environment:

| Var | Purpose |
|-----|---------|
| `CAROUSEL_API_KEYS` | bootstrap **admin** keys (`name:key,...`); empty ⇒ only DB keys work |
| `CAROUSEL_KEY_PEPPER` | optional HMAC pepper for stored key hashes |
| `PUBLIC_BASE_URL` | public origin for absolute slide URLs (behind a proxy/Funnel) |
| `CAROUSEL_API_RATE_LIMIT` / `_LIGHT` | per-key rate-limit tiers |
| `CAROUSEL_API_CORS` | CORS origins (default `*`; for browsers use a BFF — see examples) |
| `CAROUSEL_WEBHOOK_SECRET` / `_ALLOW_HOSTS` | webhook signing / private-receiver allowlist |
| `CAROUSEL_API_JOB_WORKERS` / `_TTL` | async render concurrency / job retention |

**Provision the first key:** set `CAROUSEL_API_KEYS=admin:$(openssl rand -hex 24)`,
then use that admin key to `POST /api/v1/api-keys` for each consumer. Rotate by
adding a new key, handing it over, then revoking the old.

Keys are never logged (only the key *name* appears in access logs). Expose the
service via the Tailscale Funnel — see [DEPLOY.md](../DEPLOY.md).

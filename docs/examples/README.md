# Carousel Studio API — examples

Copy-paste starters for integrating with the public API. Full reference:
[../API.md](../API.md).

| File | What it shows |
|------|---------------|
| [`curl.sh`](curl.sh) | End-to-end with curl + jq: create key → discovery → async render → poll → fetch/zip + cursor-paginated list |
| [`carousel_client.py`](carousel_client.py) | Minimal Python client (`requests`) — `render_and_wait`, `get_run`, `list_runs` (cursor), `export_zip`, `create_key` |
| [`bff_proxy.mjs`](bff_proxy.mjs) | Node Backend-for-Frontend proxy that keeps the API key server-side |
| [`browser.ts`](browser.ts) | Browser client that talks to the BFF (no key in the browser); typed with `Envelope<T>` |
| [`webhook_receiver.py`](webhook_receiver.py) | Stdlib webhook receiver with HMAC signature verification |

## Response envelope

Every `/api/v1` JSON response is wrapped:

```json
{ "success": true, "data": <payload>, "meta": { "request_id": "ab12cd34" } }
```

Errors use `success: false` with an `error` object instead of `data`. Always
read `response["data"]` (Python) / `response.data` (JS) to reach the payload.

## Quick start

```bash
# 1. Provision a key (requires bootstrap admin key from CAROUSEL_API_KEYS env)
curl -s -H "X-API-Key: $ADMIN_KEY" -H 'Content-Type: application/json' \
  -d '{"name":"my_service","scopes":["read","write"]}' \
  http://localhost:8000/api/v1/api-keys | jq .data.key

# 2. Python client (smoke test against a local server)
pip install requests
CAROUSEL_BASE=http://localhost:8000 CAROUSEL_KEY=<key-from-step-1> \
  python carousel_client.py f1 newsflash

# 3. curl cookbook
ADMIN_KEY=<admin-key> BASE=http://localhost:8000 ./curl.sh
```

## Building a browser frontend?

Never ship the API key to the browser. Run the BFF proxy, then point the
browser client at it:

```bash
CAROUSEL_BASE=https://your-app.example.com CAROUSEL_KEY=your-api-key \
  node bff_proxy.mjs        # :8787, holds the key
```

## Generate a typed client

The OpenAPI 3.1 spec is served at `/api/v1/openapi.json` and imports natively
into Postman / Insomnia. To generate a typed SDK in any language:

```bash
npx @openapitools/openapi-generator-cli generate \
  -i https://your-app.example.com/api/v1/openapi.json \
  -g python -o ./carousel-sdk     # or -g typescript-fetch, -g go, ...
```

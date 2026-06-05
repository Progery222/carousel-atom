# Carousel Studio API — examples

Copy-paste starters for integrating with the public API. Full reference:
[../API.md](../API.md).

| File | What it shows |
|------|---------------|
| [`curl.sh`](curl.sh) | End-to-end with curl + jq: discovery → async render → poll → fetch/zip |
| [`carousel_client.py`](carousel_client.py) | Minimal Python client (`requests`) — `render_and_wait`, `get_run`, `export_zip` |
| [`bff_proxy.mjs`](bff_proxy.mjs) | Node Backend-for-Frontend proxy that keeps the API key server-side |
| [`browser.ts`](browser.ts) | Browser client that talks to the BFF (no key in the browser) |
| [`webhook_receiver.py`](webhook_receiver.py) | Stdlib webhook receiver with HMAC signature verification |

## Quick start

```bash
# Python client (smoke test against a local server)
pip install requests
CAROUSEL_BASE=http://localhost:8000 CAROUSEL_KEY=k1 \
  python carousel_client.py f1 newsflash

# curl cookbook
BASE=http://localhost:8000 KEY=k1 ./curl.sh
```

## Building a browser frontend?

Never ship the API key to the browser. Run the BFF proxy, then point the
browser client at it:

```bash
CAROUSEL_BASE=https://your-app.example.com CAROUSEL_KEY=your-api-key \
  node bff_proxy.mjs        # :8787, holds the key
```

See [../API.md → Browsers, CORS & key safety](../API.md#browsers-cors--key-safety).

## Generate a typed client

The OpenAPI 3.1 spec is served at `/api/v1/openapi.json` and imports natively
into Postman / Insomnia. To generate a typed SDK in any language:

```bash
npx @openapitools/openapi-generator-cli generate \
  -i https://your-app.example.com/api/v1/openapi.json \
  -g python -o ./carousel-sdk     # or -g typescript-fetch, -g go, …
```

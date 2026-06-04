<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-04 | Updated: 2026-06-04 -->

# api

## Purpose
The FastAPI surface for the backend. Provides two tiers over one set of shared implementation functions: **internal routes** (consumed by the studio frontend, with rich error detail) and the **public `/api/v1` router** (server-to-server, with `X-API-Key` auth, slowapi rate limiting, and a unified error envelope). Also mounts static output and the built frontend SPA.

## Key Files
| File | Description |
|------|-------------|
| `server.py` | FastAPI app init (~686 lines). Lifespan hook (startup pruning + LLM rewriter setup), shared impl funcs (`list_topics_impl`, `list_designs_impl`, `preview_impl`, `render_impl`, `render_edit_impl`, `render_partial_impl`), internal routes, `/api/v1` error handler + request-ID middleware, static mounts for `/output` and the SPA. |
| `v1.py` | Public `/api/v1` router — thin wrappers over `server.py` impl funcs. Routes: GET `/topics` `/designs` `/preview/articles` (LIGHT), POST `/render` `/render/edit` `/render/partial` + GET `/export/{run_id}.zip` (HEAVY), auth-free GET `/health`. |
| `schemas.py` | Pydantic request/response models (~13). Uses `Optional[X]` (not `X \| None`) for Python 3.9 compatibility. |
| `auth.py` | `verify_api_key` dependency: reads `CAROUSEL_API_KEYS` (comma-separated, optional `name:key` labels), compares with `hmac.compare_digest`, raises 401/503. |
| `rate_limit.py` | slowapi limiter; key-func buckets by API-key name or IP. `HEAVY_LIMIT` (30/min) for renders/ZIP, `LIGHT_LIMIT` (120/min) for discovery/preview. |
| `__init__.py` | Empty package marker. |

## Internal routes (studio frontend)
`POST /render`, `POST /render/edit`, `POST /render/partial`, `GET /preview/articles`, `GET /runs`, `POST /dedup/reset/{topic}`, `POST /dedup/prune`, `GET /schedule/due`, `POST /schedule/trigger`, `POST /llm/rewrite-headline`, `POST /deliver/{run_id}`, `POST /upload-image`, `GET /health`. Discovery (`GET /topics`, `GET /designs`, `GET /deliveries`) is shared with the public tier.

## For AI Agents

### Working In This Directory
- **Use `Optional[X]`, never `X | None`** in `schemas.py` — runtime pydantic must work on Python 3.9 (PEP 604 isn't a valid runtime type expression there).
- Internal and public routes share `*_impl()` functions. The render impls take a `base=""` param for absolute URL construction (`/api/v1` slide URLs). Changes must hold for **both** call sites.
- slowapi's `SlowAPIMiddleware` is deliberately **not** registered (a registered middleware would flag requests so the `@limiter.limit(...)` decorators skip). Decorator-based limits work standalone — don't add the middleware.
- The SPA static mount at `/` (with index.html fallback) must stay **last** — any route registered after it is shadowed.
- `/upload-image` validates with magic-byte check **and** `PIL.Image.verify()`; never trust content-type or filename.
- The `/api/v1` error handler maps `HTTPException.detail` into `{"error": {"code", "message", "request_id"}}`; every `/api/v1` request gets an `X-Request-ID`.

### Testing Requirements
- `cd backend && pytest tests/test_api_v1.py -q` covers auth, rate limiting, ZIP export, OpenAPI schema, and error envelopes. Run it after any route, auth, or schema change.

### Common Patterns
- Lifespan async context manager for one-time init; decorator-based per-endpoint rate limits; shared impl funcs to keep internal/public tiers DRY.

## Dependencies

### Internal
- `core.pipeline` (`run_once`, `select_fresh_candidates`, `preview_articles`), `core.dedup`, `core.scheduler`, `core.llm`, `core.delivery`, `core.topic_loader`, `core.parsers.base` (`Article`), and the `designs` registry.

### External
- FastAPI, Pydantic, slowapi, Starlette (middleware / static / exception handling), Pillow (upload validation).

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->

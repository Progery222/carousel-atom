<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-04 | Updated: 2026-06-04 -->

# backend

## Purpose
The FastAPI service that powers Carousel Studio. It collects news from RSS / HTML / NewsAPI sources, enriches and filters them (image-quality paranoid), scores and balances them, renders PNG carousel slides through a pluggable design engine, generates captions, and optionally delivers to Telegram. Exposes both an internal API (for the studio frontend) and a public, rate-limited, API-key-authed `/api/v1` surface. Runs on port 8000.

## Key Files
| File | Description |
|------|-------------|
| `pyproject.toml` | Package config. Python ≥ 3.11. Deps: pillow, requests, beautifulsoup4, feedparser, pyyaml, python-dotenv, pytz, fastapi, uvicorn, slowapi. Packages: `core`, `core.parsers`, `designs`, `api`. |

## Subdirectories
| Directory | Purpose |
|-----------|---------|
| `api/` | FastAPI app, routes, schemas, auth, rate limiting (see `api/AGENTS.md`) |
| `core/` | Pipeline orchestration, parsers, image/text/quality logic, dedup, delivery (see `core/AGENTS.md`) |
| `designs/` | Pluggable carousel render engines, one module per design (see `designs/AGENTS.md`) |
| `tests/` | pytest suite covering quality, text, image, parsers, scheduler, API (see `tests/AGENTS.md`) |
| `topics/` | One directory per topic, each with a `topic.yaml` config (see `topics/AGENTS.md`) |
| `data/` | Runtime output (rendered runs, SQLite dedup store) — gitignored, not documented |

## For AI Agents

### Working In This Directory
- The pipeline's single entry point is `core.pipeline.run_once(topic_slug, design_slug, ...)`. Trace the 7 stages there before changing anything mid-pipeline.
- Uvicorn is launched from `backend/` (cwd), so imports use top-level package names (`from core...`, `from api...`, `from designs...`) — **not** `backend.core`.
- `from __future__ import annotations` is used throughout. Logging is via `core.log.get_logger("namespace")`, never `print`.
- `api/` code deliberately uses `Optional[X]` instead of `X | None` for pydantic compatibility on Python 3.9 — keep that pattern in API schemas.
- The two legacy design files (`designs/_newsflash_legacy.py`, `designs/_viral_roundup_legacy.py`) are kept for reference but **not registered**. Don't import from them.

### Testing Requirements
- `cd backend && pytest -q` for the full suite; `pytest tests/test_quality.py::test_name -v` for a single test.
- There is no auto-runner; run tests manually before claiming completion.

### Common Patterns
- Parallelism is via `ThreadPoolExecutor` (not async) — collect, enrich, and verify stages each fan out (max 8 workers); image search uses max 4.
- All outbound HTTP goes through `core.http` (shared retry session + SSRF gate), so the download/verify cache hits across pipeline and designs.
- Heavy use of dataclasses for config and article shapes (`Article`, `TopicConfig`, `HookCopy`, etc.).

## Dependencies

### Internal
- `api/` orchestrates `core/` (pipeline, dedup, scheduler, delivery, llm) and `designs/` (registry).
- `designs/` consume many `core/` helpers (http, image, text, typography, copy, quality).

### External
- FastAPI + Uvicorn (server), Pillow (rendering), requests + urllib3 (HTTP), BeautifulSoup4 (scraping), feedparser (RSS), PyYAML (topic config), slowapi (rate limiting), pytz/zoneinfo (scheduling).

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->

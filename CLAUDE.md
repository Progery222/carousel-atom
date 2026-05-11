# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Carousel Studio is a local Mac/Linux app that turns RSS / HTML / NewsAPI news feeds into ready-to-post TikTok / Instagram carousels. Two services, REST between them:

- `backend/` — FastAPI + Pillow, port 8000
- `frontend/` — Vite + React 19 + Tailwind + TypeScript, port 5173

The user picks a topic and a design in the frontend, the backend pulls fresh news → enriches → filters → scores → renders PNG slides + caption, the user edits, then exports a ZIP.

## Running and developing

Both `dev.sh` and `Start Carousel Studio.command` launch both servers, install deps if missing, and stream logs. The `.command` is the user-facing entry point on macOS; `dev.sh` is what it executes.

Manual run (from the repo root):

```bash
# Backend (requires Python 3.11+)
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e .
uvicorn api.server:app --reload --port 8000

# Frontend (separate terminal)
cd frontend
npm install
npm run dev
```

Or use `make backend`, `make frontend`, `make install`, `make test`, `make prune`.

**Note:** `dev.sh` deliberately skips `pip install -e .` and installs runtime deps directly (see comment in `dev.sh:6-9`). Uvicorn is launched from `backend/` so `api`, `core`, `designs` are importable via cwd.

## Tests

```bash
cd backend && pytest -q                    # full suite
cd backend && pytest tests/test_quality.py # single file
cd backend && pytest tests/test_quality.py::test_name -v
```

There is no frontend test suite. `npm run lint` (eslint) and `npm run build` (tsc + vite build) are the only frontend checks.

The global instructions mention `uv run ruff ...` for linting/formatting — that project convention does **not** apply here. This repo has no ruff config and uses plain `pip`/`venv`, not `uv`.

## Architecture

### Backend pipeline (`backend/core/pipeline.py`)

Single entry point: `run_once(topic_slug, design_slug, ...)`. Stages:

1. **Collect** — `_collect()` fetches every enabled source in parallel (ThreadPoolExecutor, max 8 workers). Sources are `rss` / `html` / `newsapi`.
2. **Fresh filter** — `_select_fresh()` drops anything in the SQLite seen-store (`core/dedup.py`, WAL mode). Optional `cross_topic_dedup` checks all topics, not just this one.
3. **Enrich & filter** — `_enrich_and_filter()` runs three parallel stages: og:image/og:description enrichment → image-search fallback (Wikimedia/Pexels/Unsplash) → image-download verification. Then `core.quality.passes_filters` + `_dedupe_images`.
4. **Score & balance** — `core.quality.score_article` + `balance_sources` (round-robin so one outlet doesn't dominate a carousel).
5. **Render** — the chosen design's `render(topic, articles, output_dir)` writes PNGs to `backend/data/output/<run_id>/`.
6. **Caption** — `core.caption_engine.render_caption` with optional LLM rewrite if `LLM_API_KEY` set.
7. **Deliver (optional)** — Telegram adapter when `deliver="telegram"` is passed.

The pipeline is image-quality paranoid: low-res detection, image dedup (e.g. F1.com reuses the same studio shot), and download verification all live here. `CAROUSEL_PHOTO_FILTER=1` enables an extra photo-vs-graphic filter (off by default — strict enough to starve a carousel on a slow news day).

### Designs (`backend/designs/`)

A design is a `Design` dataclass (`designs/base.py`) wrapping a render function with signature `(topic, articles, output_dir) -> list[str]`. Registered in `designs/__init__.py`; registration order = display order in the UI.

To add a design: implement the function, import + register in `designs/__init__.py`. Use `core.http.download_images_parallel` for image fetching, `core.typography.fit_font` for headlines, `core.copy.hook_copy` / `core.copy.cta_copy` for hook + CTA text (so YAML overrides apply automatically).

### Topics (`backend/topics/<slug>/topic.yaml`)

Each topic is a directory with a `topic.yaml` (sources, brand colors, hooks, schedule, optional copy overrides). Loaded via `core.topic_loader.load_topic` into `TopicConfig`. Restart the backend to pick up new topics — they appear in the sidebar automatically. See `README.md:117-152` for the schema.

`env:CHAT_F1` references in YAML are resolved against environment variables (used for per-topic Telegram chat IDs).

### API (`backend/api/server.py`)

FastAPI routes most worth knowing:

- `POST /render` — full pipeline run.
- `POST /render/edit` — re-render with user-edited articles (no network fetch).
- `POST /render/partial` — re-roll specific slots (pass `null` for slots to refresh, locked articles for slots to keep).
- `GET /preview/articles` — dry-run candidate list for the cherry-picker modal.
- `GET /schedule/due`, `POST /schedule/trigger` — cron-style scheduled posting (see `README.md:170-185`).
- `POST /dedup/reset`, `POST /dedup/prune` — seen-store maintenance.

Static mount: `/output/...` serves rendered slides from `backend/data/output/`.

### Frontend state machine (`frontend/src/App.tsx`)

State: pick topic → pick design → render → optionally edit slides → export ZIP. History is `localStorage`-backed (`HISTORY_KEY = "carousel-studio:runs:v1"`). The `api.ts` module is the only place that talks to the backend.

Hotkeys: G=generate/re-roll, B=batch x3, P=candidate previewer, E=toggle editor, V=toggle strip/grid view, Esc=close modal.

## Environment variables

Optional integrations — copy `.env.example` → `.env`. The vars worth knowing:

- `LLM_API_KEY` + `LLM_BASE_URL` + `LLM_MODEL` — caption rewriter and the "Punchier / Factual / Hook / RU translate" buttons in the slide editor. Any OpenAI-compatible endpoint.
- `TELEGRAM_BOT_TOKEN` + `CHAT_<TOPIC>` — Telegram delivery.
- `NEWSAPI_KEY` — enables `kind: newsapi` source entries.
- `PEXELS_API_KEY`, `UNSPLASH_ACCESS_KEY` — image-search fallback for articles with no usable photo. Wikimedia works without a key.
- `CAROUSEL_PHOTO_FILTER` — strict photo-vs-graphic filter, off by default.
- `CAROUSEL_PRUNE_DAYS` — seen-store auto-prune age (default 180).
- `CAROUSEL_CORS` — comma-separated extra CORS origins beyond `localhost:5173`.
- `VITE_CAROUSEL_API` — frontend's backend base URL (default `http://localhost:8000`).

## Conventions worth knowing

- **Python ≥ 3.11** per `pyproject.toml`, but `api/server.py` deliberately uses `Optional[X]` instead of `X | None` for pydantic compatibility on 3.9 — keep that pattern in API schemas (see comment at `server.py:153-156`).
- `from __future__ import annotations` is used throughout the backend.
- Logging via `core.log.get_logger("namespace")`, not `print`. Default level `INFO`, override with `CAROUSEL_LOG`.
- `core.http._download_one` / `download_images_parallel` is the shared session with retries — designs and the pipeline both use it so the verify cache hits.
- The legacy designs `_newsflash_legacy.py` and `_viral_roundup_legacy.py` are kept for reference but not registered. Don't import from them.

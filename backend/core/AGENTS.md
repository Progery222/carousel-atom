<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-04 | Updated: 2026-06-04 -->

# core

## Purpose
The engine room of the backend. Contains the pipeline orchestrator and every supporting module: source parsing, image processing and search, text/headline cleanup, quality gating and scoring, the SQLite dedup store, the shared HTTP session, the topic-config loader, typography, captioning, optional LLM rewriting, scheduling, and delivery adapters. The image-quality-paranoid logic (low-res detection, press-photo classification, dedup of reused studio shots) lives here.

## Key Files
| File | Description |
|------|-------------|
| `pipeline.py` | Orchestrator. `run_once()` runs collect → fresh-filter → enrich/filter → score/balance → render → caption → optional deliver. Also `select_fresh_candidates()`, `preview_articles()`, `prune_old_runs()`. |
| `parsers/` | Source parsers + article enrichment (RSS / HTML / NewsAPI) — see `parsers/AGENTS.md`. |
| `quality.py` | Hard filters (non-news, too short, no image, stale) + soft scoring + severity classification, news icon/emoji selection, `balance_sources` round-robin. |
| `text.py` | Headline cleanup (strips publisher tails), trending-term/entity extraction, hashtagify, description truncation, TikTok-voice rewriting. Stdlib-only. |
| `image.py` | Pillow image ops: `smart_cover` (saliency crop), `is_press_photograph` (crest-vs-photo), `darken_band_under_text`, brightness probes, low-res heuristics. |
| `image_search.py` | Fallback image search via Wikimedia / Pexels / Unsplash by extracted title entities. |
| `http.py` | Process-wide retry-enabled `requests.Session` + SSRF gate (`is_public_url`), `download_images_parallel`, `prune_dir_older_than`. All outbound HTTP funnels here. |
| `dedup.py` | SQLite seen-store (WAL mode, 5s busy_timeout): `is_seen`, `is_seen_anywhere`, `mark_seen`, `log_post`, `prune_seen`. |
| `topic_loader.py` | Loads `topics/<slug>/topic.yaml` → `TopicConfig` (+ `Source`, `Brand`, `CaptionConfig`, etc.); resolves `env:VAR` references. |
| `copy.py` | Hook/CTA copy pools (`HookCopy`, `CtaCopy`) with topic override → tone fallback → global defaults. |
| `caption_engine.py` | `render_caption()` — intro + dynamic hashtags + optional LLM rewrite; `set_llm_rewriter()` hook. |
| `typography.py` | Balanced text wrapping + binary-search font-size fitting (`fit_font`, `balanced_wrap`). |
| `llm.py` | Optional OpenAI-compatible rewriter (`caption_rewriter`, `headline_rewriter`); env-driven, fails silently. |
| `scheduler.py` | `run_due_topics()` — renders topics whose `schedule.send_hours` match local (timezone-aware) time. |
| `log.py` | `get_logger()` — stdlib logger namespaced under `carousel.*`; level via `CAROUSEL_LOG`. |
| `__init__.py` | Empty package marker. |

## Subdirectories
| Directory | Purpose |
|-----------|---------|
| `parsers/` | RSS / HTML / NewsAPI source parsers + the `Article` dataclass (see `parsers/AGENTS.md`) |
| `delivery/` | Output adapters (currently Telegram) (see `delivery/AGENTS.md`) |
| `assets/fonts/` | Bundled TTFs (Anton, BebasNeue, Inter-Bold, Oswald) used by designs/typography — no AGENTS.md |

## For AI Agents

### Working In This Directory
- **Circular-import guard**: `quality.py` lazy-imports `image.py` helpers, and `topic_loader.py` lazy-imports `core.copy`. Don't hoist these to module level.
- **SSRF gate is mandatory**: every URL from an untrusted source (RSS, scraped pages, uploaded images) must pass `is_public_url()` before fetch. `CAROUSEL_ALLOW_LOCAL=1` bypasses it (dev only).
- **LLM input safety**: `llm.py` never `.format()`s user text — headlines/captions are wrapped in XML tags and sanitized. Preserve this pattern.
- **Tuned thresholds**: `is_press_photograph()` (≈600 unique colors, edge-mean ≈5) and `looks_low_res()` (≈600px) are empirically calibrated. Small changes break the photo filter. Trending entity bonuses (1.0 for 3+, 0.4 for 2+) are tuned for ~5-article carousels.
- **Concurrency**: `dedup.py` relies on WAL + busy_timeout and an auto-committing context manager — don't nest transactions. `http.py` lazy-inits the session under a lock; the pipeline uses ThreadPoolExecutor (not async).
- **Article mutation**: pipeline mutates `Article` objects in place (title clean, image-URL upgrade); mutations are idempotent so `enrich_article()` is safe to call repeatedly.

### Testing Requirements
- Most logic here is unit-tested: `pytest tests/test_quality.py tests/test_text.py tests/test_image.py tests/test_image_search.py tests/test_typography.py tests/test_scheduler.py tests/test_llm.py -q`.

### Common Patterns
- `from __future__ import annotations` everywhere; logging via `get_logger(__name__)`; dataclass-heavy config; graceful degradation (enrichment/LLM/missing-key failures log and fall back, never crash the carousel).

## Dependencies

### Internal
- `pipeline.py` is the hub — it pulls in parsers, quality, text, image_search, dedup, http, llm, caption_engine, and delivery. `caption_engine`/`copy` depend on `topic_loader`; `image_search`/`llm`/`html_scraper` depend on `http`.

### External
- Pillow (image/typography), requests + urllib3 (http), BeautifulSoup4 (html scraping, via parsers), feedparser (rss), PyYAML (topic_loader), zoneinfo/pytz (scheduler).

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->

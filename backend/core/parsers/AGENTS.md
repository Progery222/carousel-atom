<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-04 | Updated: 2026-06-04 -->

# parsers

## Purpose
Source adapters that turn a configured `Source` (RSS / HTML / NewsAPI) into a list of `Article` objects, plus the per-article enrichment that scrapes og:image / og:description / timestamps and upgrades thumbnail URLs to full resolution. This is the "collect" half of the pipeline.

## Key Files
| File | Description |
|------|-------------|
| `base.py` | The `Article` dataclass (`title`, `url`, `source`, `image_url`, `description`, `published_ts`) and the shared `HEADERS` dict. |
| `rss.py` | `fetch_rss()` — feedparser-based; pulls images from media tags, enclosures, or a `<img>` in the summary. |
| `html_scraper.py` | `fetch_html()` (link extraction from a list page), `enrich_article()` (og:image/description/timestamp), `upgrade_image_url()` (publisher-specific full-res rewrites), plus `looks_low_res()` / `url_width_hint()`. |
| `newsapi.py` | `fetch_newsapi()` — NewsAPI.org query/domain/language/sort filters; requires `NEWSAPI_KEY`; drops `[Removed]` entries. |
| `__init__.py` | Re-exports `Article`, `HEADERS`, `enrich_article`, `fetch_html`, `fetch_newsapi`, `fetch_rss`. |

## For AI Agents

### Working In This Directory
- All HTTP must go through `core.http` (`get`, and `is_public_url` for SSRF) — never raw `requests`. This keeps the retry/SSRF/verify-cache behavior consistent.
- `enrich_article()` mutates the `Article` in place and is idempotent — safe to call more than once.
- `upgrade_image_url()` holds publisher-specific rewrites (e.g. BBC `/sport/600/`→`/2048/`, Guardian `/140.jpg`→`/2000.jpg`, Goal `/h2_lazy/`→`/h2_full/`). Add new publishers here, not in designs.
- Parser failures should log at warning and return what they have — a bad source must not crash collection.
- Note the lazy-import relationship: `core.quality` imports `looks_low_res` / `url_width_hint` from here (avoids a circular import with `core.image`).

### Testing Requirements
- `pytest tests/test_newsapi.py -q` covers the NewsAPI parser (mocked HTTP). RSS/HTML enrichment is exercised through pipeline integration; mock `core.http` for new unit tests.

### Common Patterns
- `from __future__ import annotations`; logger names like `carousel.parser.html` / `.rss`; return `list[Article]`.

## Dependencies

### Internal
- `core.http` (session, `is_public_url`), `core.log`. Consumed by `core.pipeline` and re-exported for the rest of the backend.

### External
- feedparser (rss), BeautifulSoup4 (html_scraper), requests (via `core.http`).

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->

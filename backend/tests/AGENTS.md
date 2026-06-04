<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-04 | Updated: 2026-06-04 -->

# tests

## Purpose
The pytest suite for the backend. Coverage centers on the deterministic, testable units — text/headline cleanup, quality gating and scoring, image heuristics, parsers, typography, scheduling, the LLM rewriter (mocked), and the public API. The render designs themselves are not unit-tested (exercised end-to-end).

## Key Files
| File | Description |
|------|-------------|
| `test_quality.py` | Quality gate: filters (title length, image, staleness), article scoring/ranking, severity classification. |
| `test_text.py` | Headline cleanup (publisher-tail stripping, punctuation collapse), trending-term extraction, hashtag generation. |
| `test_punchy.py` | Headline rewriter (drops SEO clauses, "Formula 1"→"F1", contractions) and accent-phrase picker. |
| `test_copy.py` | Hook/CTA copy defaults render correctly; YAML overrides take precedence. |
| `test_image.py` | `smart_cover` saliency crop — synthetic busy-corner images verify crop bias. |
| `test_image_search.py` | Image-search fallback chain: entity extraction + Wikimedia/Pexels/Unsplash parsing. |
| `test_llm.py` | LLM caption rewriter with mocked HTTP — API-key handling and fallback on error. |
| `test_newsapi.py` | NewsAPI parser (mocked HTTP) — filtering and removal of `[Removed]` entries. |
| `test_news_icon.py` | News-icon classifier picks badge symbols (!, ", X, ?) by article wording. |
| `test_scheduler.py` | Due-window logic for topic scheduling (timezone-aware), no rendering. |
| `test_typography.py` | Balanced-wrap text wrapper using Pillow's default bitmap font. |
| `test_api_v1.py` | Public `/api/v1`: auth headers, rate limiting, ZIP export, OpenAPI schema, error envelopes. |
| `__init__.py` | Empty package marker. |

## For AI Agents

### Working In This Directory
- Run from the backend root so imports resolve: `cd backend && pytest -q`. Single file: `pytest tests/test_quality.py`. Single test: `pytest tests/test_quality.py::test_name -v`.
- Tests mock the HTTP layer (`core.http`) rather than hitting the network — keep new tests offline and deterministic.
- Image and typography tests build synthetic Pillow images / use the default bitmap font rather than relying on bundled TTFs — follow that approach to stay font-environment-independent.
- When you change a tuned heuristic in `core/` (quality thresholds, photo filter, entity bonuses), update the corresponding test's expectations rather than loosening assertions.

### Testing Requirements
- This **is** the test suite; `make test` runs `pytest -q`. There is no frontend test suite.

### Common Patterns
- Plain `pytest` functions (no fixtures-heavy setup), HTTP mocked, synthetic inputs, assertions on cleaned/scored output.

## Dependencies

### Internal
- Imports the modules under test from `core/` and `api/` (e.g. `core.quality`, `core.text`, `core.image`, `api.server`/`api.v1`).

### External
- pytest, Pillow (synthetic images), the FastAPI `TestClient` (for `test_api_v1.py`).

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->

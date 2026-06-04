<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-04 | Updated: 2026-06-04 -->

# designs

## Purpose
The pluggable carousel render engines. Each design is a `Design` dataclass wrapping a `render(topic, articles, output_dir) -> list[str]` function that writes PNG slides and returns their paths. The registry in `__init__.py` controls which designs exist and the order they appear in the studio UI.

## Key Files
| File | Description |
|------|-------------|
| `__init__.py` | Registry. Imports each design and stores it in `_DESIGNS` keyed by slug; **registration order = display order**. Exports `list_designs()` and `get_design(slug)`. |
| `base.py` | The frozen `Design` dataclass (`slug`, `name`, `description`, `render`) and the `DesignRenderer` protocol: `(topic: TopicConfig, articles: list[Article], output_dir: Path) -> list[str]`. |
| `tiktok_news.py` | Close copy of @f1newsflash — hard-locked 1080×1920, photo top + fade-to-black, circular topic emblem, punchy headline. **Default design (first in registry).** |
| `newsflash.py` | Full-bleed photo, bold headline with last words in red, footer + segmented progress bar (delegates to the legacy 4:5 renderer). |
| `viral_roundup.py` | Viral hook + ranked countdown (#5→#1), heavy overlays, giant orange-red headlines; hook + ranked news + CTA. |
| `quote_card.py` | Pull-quote treatment: blurred background, large quote glyph, byline ribbon; severity-aware tone. |
| `premium_light.py` | Magazine off-white layout, dark serif headline, small thumbnail, accent pill; calm tone for lifestyle/features. |
| `story_mode.py` | Narrative arc: chapter labels, dark gradient, collage cover, reflective tone; severity-aware. |
| `blueprint.py` | Technical-drawing poster: edge-detected line-art on cobalt, engineering grid, dimension ticks; hard-locked 1080×1920. |
| `_newsflash_legacy.py` | Original 4:5 newsflash renderer. **Not registered** — kept for reference; `newsflash.py` delegates to it. Don't add to the registry. |
| `_viral_roundup_legacy.py` | Original NBA roundup (hardcoded font path). **Not registered** — reference only. Don't import. |

## For AI Agents

### Working In This Directory
- **Adding a design**: write `my_design.py` with a `render(topic, articles, output_dir) -> list[str]` function and a module-level `Design(slug=..., name=..., description=..., render=render)`; import it in `__init__.py` and add it to `_DESIGNS`. Restart the backend — it then appears in `GET /designs` and the studio picker.
- **Registration order matters** — it's the UI display order. `tiktok_news` is intentionally first (best match to the reference).
- **Never register or import the `_*_legacy.py` files.**
- `tiktok_news` and `blueprint` **hard-lock** the canvas to 1080×1920, ignoring `topic.carousel` dimensions — keep that.
- `render()` must **always return a list** of string paths, even for one slide. Save as `output_dir / f"slide_{N}.png"`, 1-indexed.
- Handle missing images gracefully — `article.image_url` may be empty/None.
- Use the shared core helpers (below) rather than re-implementing — e.g. `download_images_parallel`, `fit_font`, `hook_copy`/`cta_copy` (so YAML copy overrides apply). Severity-aware designs branch tone via `core.quality.severity_of()` — don't hardcode tone.

### Testing Requirements
- No per-design unit tests; designs are exercised end-to-end via `pipeline.run_once`. After changes, render a real carousel (`POST /render`) and eyeball the slides; compare against the references in `preview/`.

### Common Patterns
- Standard shape: `mkdir` output dir → `download_images_parallel(...)` into `_images/` → build intro → per-article slides → outro → return paths.
- Font loading uses a local `_font(path, size, fallback)` helper with a cross-platform fallback TTF.

## Dependencies

### Internal
- `core.http` (`download_images_parallel`), `core.image` (`smart_cover`, `darken_band_under_text`), `core.typography` (`fit_font`, `balanced_wrap`), `core.text` (`clean_headline`, etc.), `core.copy` (`hook_copy`/`cta_copy`), `core.quality` (`severity_of`, news icon/emoji), `core.topic_loader` (`TopicConfig`), `core.parsers.base` (`Article`), `core.log`.

### External
- Pillow (`Image`, `ImageDraw`, `ImageFont`, `ImageOps`, `ImageFilter`), `pathlib`.

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->

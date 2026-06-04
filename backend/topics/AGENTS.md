<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-04 | Updated: 2026-06-04 -->

# topics

## Purpose
One directory per topic, each containing a `topic.yaml` that fully describes a content vertical: its news sources, brand colors and fonts, CTA/caption copy, carousel dimensions, posting schedule, and delivery target. Topics are data, not code — adding a directory with a valid `topic.yaml` adds a topic to the studio sidebar (after a backend restart). Loaded via `core.topic_loader.load_topic` into a `TopicConfig`.

## Topic slugs (20)
`ai`, `celebrity`, `crypto`, `f1`, `fashion`, `finance`, `fitness`, `food`, `gaming`, `lifestyle`, `mlb`, `movies`, `music`, `nba`, `nfl`, `nhl`, `science`, `soccer`, `tech`, `ufc`.

Most topics are a lone `topic.yaml`. A few ship custom `assets/` — `f1/` (logo.png + Inter fonts), `lifestyle/`, `nba/`, `soccer/`, `ufc/` (Inter fonts). Topics may reference fonts from a sibling topic via a relative path (e.g. `../f1/assets/fonts/Inter-ExtraBold.ttf`).

## topic.yaml schema (essentials)
```yaml
slug: f1
display_name: Formula 1
language: en
sources:                       # rss | html | newsapi
  - kind: rss
    name: BBC Sport F1
    feed: https://...          # html uses `url:` + `article_pattern:` regex
    enabled: true              # optional, default true
blocklist: ["keyword"]         # optional title-substring filter
brand:
  logo: assets/logo.png        # optional, relative to this topic dir
  colors: { bg: "#...", accent: "#...", accent_light: "#...", text: "#..." }
  fonts: { headline: assets/fonts/Inter-ExtraBold.ttf, body: assets/fonts/Inter-Bold.ttf }
cta: { headline: "...", subtext: "..." }
caption:
  intro: "..."                 # static caption opener
  hashtags: [ ... ]            # default hashtags
  style: bullet
  llm_rewrite: false           # optional
carousel: { slides_per_carousel: 5, news_per_carousel: 4, width: 1080, height: 1920 }
schedule: { timezone: "Europe/London", send_hours: [9, 18] }   # local-TZ hours
delivery: { telegram_chat: "env:CHAT_F1" }                     # resolved from env at runtime
hook_pool:                     # optional copy override
  viral:
    - { badge: "BREAKING", line1: "{n} stories", ... }
```

## For AI Agents

### Working In This Directory
- **Restart the backend** to pick up a new or renamed topic directory — topics are discovered at startup, not per-request.
- `env:CHAT_F1`-style values (in `delivery.telegram_chat`, and anywhere env indirection is supported) are resolved against environment variables at load time. The chat id lives in `.env` / the environment, not the YAML.
- Asset paths are relative to the topic directory. If you reference a font/logo, make sure it exists (or points at a sibling topic's `assets/`).
- Designs read `brand.colors`, `brand.fonts`, and `carousel.{width,height}` — but `tiktok_news` and `blueprint` hard-lock 1080×1920 regardless. Don't expect those two to honor custom dimensions.
- This is config, not code: validate by loading the topic (`core.topic_loader.load_topic`) and running a `POST /render` for it, not by writing Python.

### Testing Requirements
- No per-topic tests. After editing a `topic.yaml`, restart the backend and render the topic to confirm sources fetch and the carousel builds.

### Common Patterns
- `sources` mix `rss`, `html` (needs `article_pattern`), and `newsapi` (needs `NEWSAPI_KEY`). `copy`/`hook_pool` overrides replace the global defaults for that topic.

## Dependencies

### Internal
- Consumed by `core.topic_loader` → `TopicConfig`; used throughout `core.pipeline`, `designs/`, `core.caption_engine`, `core.copy`, and `core.scheduler`.

### External
- PyYAML (parsing). Custom fonts are TTFs; logos are PNGs.

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->

# Carousel Studio

A small local app that turns RSS / HTML news feeds into ready-to-post
TikTok / Instagram carousels. Pick a topic, pick a design, hit *Generate*,
edit if needed, drop the ZIP into your scheduler.

```
┌──────────── frontend (Vite + React 19 + Tailwind, port 5173) ───────────┐
│  Topic picker · Design picker · History  │   Live carousel preview      │
│                                          │   Editable slide list        │
│                                          │   Caption editor + ZIP       │
└──────────────────────────────────────────┴──────────────────────────────┘
                                  │   REST
┌──────────── backend (FastAPI + Pillow, port 8000) ──────────────────────┐
│  /topics  /designs  /render  /render/edit  /preview/articles            │
│  /runs    /dedup/{reset,prune}  /deliveries  /health                    │
│  /schedule/{due,trigger}                                                │
│                                                                          │
│  pipeline:  RSS|HTML|NewsAPI → enrich (og:* tags) → quality + severity  │
│             → score → round-robin balance → smart-crop image fetch      │
│             (parallel) → render PNGs → optional Telegram delivery       │
│                                                                          │
│  storage:   SQLite (WAL) — seen-store, posts log, auto-prune on boot    │
└─────────────────────────────────────────────────────────────────────────┘
```

## Repo layout

```
backend/
  api/server.py            FastAPI app
  core/
    pipeline.py            news → filter → render → caption
    parsers/               RSS + HTML scrapers, og:* enrichment
    quality.py             hard filters + soft scoring + severity gate
    dedup.py               SQLite seen-store + posts log (WAL mode)
    caption_engine.py      template captions + trend-aware hashtags
    text.py                clean_headline, extract_trending_terms
    typography.py          balanced wrap, fit_font helper
    copy.py                hook / CTA copy pools (per topic, with defaults)
    http.py                shared session w/ retries + parallel image dl
    log.py                 stdlib logger ("carousel.*" namespace)
    topic_loader.py        topic.yaml → TopicConfig dataclass
  designs/
    base.py                Design protocol
    newsflash.py           classic dark "newsflash" template
    viral_roundup.py       hook + ranked countdown + CTA
    quote_card.py          editorial pull-quote template
    premium_light.py       magazine-style cream layout
    story_mode.py          chapterised narrative arc
  topics/<slug>/topic.yaml sources, brand colours, hooks, schedule
  pyproject.toml
  tests/                   pytest — quality, text, copy, image, llm,
                           newsapi, scheduler, typography

frontend/
  src/
    App.tsx                state machine: pick → render → edit → export
    api.ts                 typed fetch wrappers
    components/
      TopicPicker.tsx
      DesignPicker.tsx
      CarouselPreview.tsx  strip ↔ grid toggle
      SlideEditor.tsx      title / image / order / drop
      HistoryPanel.tsx     localStorage-backed run history
      ExportPanel.tsx      caption editor + ZIP download
      CandidatePanel.tsx   /preview/articles cherry-picker (modal)
      StatusPill.tsx       polled /health snapshot in the header
      Toast.tsx            timed error notification
```

### Hotkeys

| key | action                                                |
|-----|-------------------------------------------------------|
| G   | Generate / Re-roll                                    |
| B   | Generate × 3 (back-to-back)                           |
| P   | Open the candidate previewer (`/preview/articles`)    |
| E   | Toggle slide editor                                   |
| V   | Toggle strip ↔ grid view                              |
| Esc | Close any open modal                                  |

## Run it

```bash
# 1. Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e .
uvicorn api.server:app --reload --port 8000

# 2. Frontend
cd frontend
npm install
npm run dev
# → http://localhost:5173
```

Optional environment:

| variable                | default                             | what it does                                       |
|-------------------------|-------------------------------------|----------------------------------------------------|
| `CAROUSEL_LOG`          | `INFO`                              | logging level (`DEBUG`/`INFO`/`WARNING`)          |
| `CAROUSEL_CORS`         | `http://localhost:5173,…127.0.0.1…` | extra CORS origins, comma-sep                      |
| `CAROUSEL_PRUNE_DAYS`   | `180`                               | auto-prune the seen-store at startup               |
| `VITE_CAROUSEL_API`     | `http://localhost:8000`             | base URL the frontend calls                        |
| `TELEGRAM_BOT_TOKEN`    | —                                   | enables the Telegram delivery adapter              |
| `CHAT_F1`, `CHAT_NBA`…  | —                                   | per-topic chat IDs referenced from `topic.yaml`    |
| `LLM_API_KEY`           | —                                   | enables the OpenAI-compatible caption rewriter     |
| `LLM_BASE_URL`          | `https://api.openai.com/v1`         | OpenAI / Anthropic-via-proxy / Groq / Ollama       |
| `LLM_MODEL`             | `gpt-4o-mini`                       | model name passed to the chat-completions call     |
| `NEWSAPI_KEY`           | —                                   | enables `kind: newsapi` source entries             |

Run `make help` for one-line shortcuts.

## Adding a topic

Drop a `topic.yaml` into `backend/topics/<slug>/`:

```yaml
slug: tech
display_name: "Tech Daily"
language: en
sources:
  - {kind: rss, name: TechCrunch, feed: https://techcrunch.com/feed/}
brand:
  colors: {bg: "#0A0A0A", accent: "#7C3AED", accent_light: "#C4B5FD", text: "#FFFFFF"}
  fonts:
    headline: ../f1/assets/fonts/Inter-ExtraBold.ttf
    body:     ../f1/assets/fonts/Inter-Bold.ttf
cta:
  headline: "FOLLOW\nFOR DAILY\nTECH NEWS"
  subtext:  "EVERYTHING TECH, EVERY DAY"
caption:
  intro: "💻 TECH NEWS 💻"
  hashtags: [tech, technews, ai, startups]
  style: bullet
carousel: {slides_per_carousel: 6, news_per_carousel: 5, width: 1080, height: 1350}
schedule: {timezone: UTC, send_hours: [9, 14, 20]}

# Optional copy overrides — falls back to defaults in core/copy.py
hook_pool:
  viral:
    - {badge: "BREAKING", line1: "{n} {label} STORIES", line2: "EVERYONE",
       line3: "IS TALKING ABOUT", sub1: "From launches to leaks —",
       sub2: "this is your daily roundup", tease: "#1 IS WILD"}
cta_pool:
  viral:
    - {q1: "WHICH STORY", q2: "BLEW YOUR", q3: "MIND?",
       prompt1: "Drop your pick", prompt2: "in the comments"}
```

## Adding a design

Implement a function with this signature, register it in
`designs/__init__.py`:

```python
def render(topic: TopicConfig, articles: list[Article],
           output_dir: Path) -> list[str]:
    ...
```

Use `core.http.download_images_parallel` for image fetching,
`core.typography.fit_font` for headline rendering, and `core.copy.hook_copy`
/ `core.copy.cta_copy` for hook + CTA text so the design picks up YAML
overrides automatically.

## Cron / scheduled posting

Topics declare `schedule.send_hours: [9, 15, 21]` in `topic.yaml`. To
actually post on that cadence, hit the studio every ~30 minutes from
launchd / cron / a GitHub Action:

```bash
# every 30 minutes
*/30 * * * * curl -s -X POST http://localhost:8000/schedule/trigger \
  -H 'Content-Type: application/json' \
  -d '{"design": "newsflash", "deliver": "telegram", "window_min": 30}' \
  >/dev/null
```

`/schedule/trigger` only renders topics whose `send_hours` falls within
the given window in the topic's local timezone. `GET /schedule/due` is
a dry-run that returns the topic slugs that would fire right now.

## Tests

```bash
cd backend
pip install pytest
pytest -q
```

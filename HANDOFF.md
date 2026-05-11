# Carousel Studio — first-time setup

A local-only Mac/Linux app that turns RSS news feeds into ready-to-post
TikTok / Instagram carousels. Everything runs on your machine — no
external accounts required, no recurring subscription.

## What you need installed

| | macOS install command |
|---|---|
| **Python 3.9+** | `xcode-select --install` (comes with Command Line Tools) |
| **Node.js 18+** | `brew install node` or download from nodejs.org |
| (optional) **Homebrew** | `/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"` |

Check:
```bash
python3 --version   # should print 3.9.x or higher
node --version      # should print v18.x.x or higher
```

## First run

1. Open `Start Carousel Studio.command` by **double-clicking it in Finder**.
   - If macOS says "cannot be opened because it is from an unidentified developer" → right-click → Open → Open. Only needed once.
2. Terminal opens and starts installing dependencies (~30-60 seconds the first time):
   - Creates a Python virtual environment in `backend/.venv/`
   - Installs Python packages (`pip install fastapi uvicorn pillow ...`)
   - Installs Node packages (`npm install` in `frontend/`)
3. When both servers are ready, your default browser opens at **http://localhost:5173** automatically.
4. The studio is ready. Pick a topic and a design, press **Generate**.

## Daily use

After first setup, just **double-click `Start Carousel Studio.command`** —
takes ~3 seconds to launch. Ctrl-C in the terminal stops both servers
cleanly. Closing the terminal window also stops them.

## Optional configuration

The app works fully offline-free, but several optional integrations live
in environment variables:

| variable | what it does |
|---|---|
| `LLM_API_KEY` + `LLM_BASE_URL` | enables the ✨ LLM rewrite buttons in slide editor (Punchier / Factual / Hook / RU translate). Defaults to OpenAI gpt-4o-mini. Set to any OpenAI-compatible endpoint (OpenAI, Groq, Ollama local, etc). |
| `TELEGRAM_BOT_TOKEN` + `CHAT_<TOPIC>` | enables the "Send to Telegram" button in export panel. Create a bot via @BotFather, get its token; per-topic channel IDs go in `CHAT_F1`, `CHAT_NBA`, etc. |
| `NEWSAPI_KEY` | enables `kind: newsapi` source entries in `topic.yaml` (optional, current topics use RSS) |

Copy `.env.example` → `.env`, fill in what you want, and re-launch.

## Folder layout

```
Carousel/
├── Start Carousel Studio.command  ← double-click to run
├── dev.sh                          ← what .command actually executes
├── README.md                       ← architectural docs
├── .env.example                    ← env vars template
├── backend/
│   ├── api/server.py               ← FastAPI app
│   ├── core/                       ← pipeline, parsers, quality, llm, dedup
│   ├── designs/                    ← 7 carousel design renderers
│   ├── topics/<slug>/topic.yaml    ← per-topic source list + branding
│   └── tests/                      ← pytest suites
├── frontend/
│   ├── src/                        ← React + TypeScript + Tailwind
│   └── package.json
└── preview/                        ← reference design screenshots
```

## What's NOT in this handoff

To keep the package small and machine-independent:

| excluded | how to regenerate |
|---|---|
| `backend/.venv/` | auto-created by `dev.sh` on first run |
| `frontend/node_modules/` | auto-installed by `npm install` (also on first run) |
| `backend/data/` | seen-store + rendered outputs; created at runtime |
| `__pycache__/`, `*.pyc` | Python bytecode cache, regenerated |

So the recipient just double-clicks the launcher and waits ~1 minute.

## If something breaks

Two log files are written to the project root every run:
- `.backend.log` — uvicorn + pipeline output
- `.frontend.log` — Vite dev server output

Both are streamed to the Terminal window opened by `.command`, so you'll
see errors live. If a topic returns "no articles", an RSS feed probably
went down — check the log for warnings about specific sources.

## Topics & designs

**11 pre-configured topics** (`backend/topics/<slug>/topic.yaml`):
F1, NBA, NFL, MLB, NHL, Soccer, UFC, Lifestyle, Crypto, Tech, Movies & TV.

**7 designs** (`backend/designs/`):
- `tiktok_news` — close copy of @f1newsflash visual language (1080×1920)
- `newsflash` — full-bleed photo top, bold bottom headline (1080×1350)
- `viral_roundup` — hook + ranked countdown + CTA
- `quote_card` — editorial pull-quote
- `premium_light` — magazine-style cream layout
- `story_mode` — chapterised narrative arc with 2×3 collage cover
- `blueprint` — technical-drawing poster with edge-detected line art

Add a new topic by dropping a `topic.yaml` into `backend/topics/<slug>/`
following the existing structure — restart the backend, it appears in
the sidebar automatically.

---

That's it. Everything else is documented in `README.md`.

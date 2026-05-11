# Deploying Carousel Studio to Railway

Single-service deployment: one Docker image where FastAPI serves both the
API and the prebuilt frontend. No CORS, no two-service plumbing.

## What's in the box

| File              | Purpose                                                  |
|-------------------|----------------------------------------------------------|
| `Dockerfile`      | Multi-stage: Node builds frontend → Python runs uvicorn  |
| `railway.toml`    | Healthcheck (`/health`) + restart policy                 |
| `.dockerignore`   | Keeps build context small (no `.venv`, `node_modules`)   |
| `.gitignore`      | Excludes `backend/data/`, logs, build artifacts          |

The Python image installs Pillow's runtime deps (`libjpeg`, `libpng`,
`libwebp`, `libfreetype`) — required for the carousel renderer.

## Persistent storage

SQLite (`backend/data/factory.db`) and rendered runs (`backend/data/output/`)
must survive deploys. Mount a Railway **Volume** at `/app/backend/data`.

## Step-by-step

### 1. Push to GitHub

```bash
git init
git branch -M main
git remote add origin https://github.com/Progery222/carousel-atom.git
git add .
git commit -m "feat: production-ready release"
git push -u origin main
```

### 2. Install Railway CLI (if not yet installed)

```bash
npm i -g @railway/cli
railway --version
```

### 3. Log in and create a project

```bash
railway login          # opens a browser
railway init           # interactive: pick a project name
railway link           # if you already created the project in the dashboard
```

### 4. Deploy

There are two paths — pick one.

**A. Direct push from CLI (fastest):**

```bash
railway up
```

This uploads the current directory to Railway and builds it from the
Dockerfile. Good for the first deploy or one-off rebuilds.

**B. GitHub auto-deploy (recommended for ongoing work):**

In the Railway dashboard:
1. Project → **+ New** → **GitHub Repo** → pick `Progery222/carousel-atom`
2. Railway detects the `Dockerfile` and `railway.toml` automatically
3. Every push to `main` triggers a fresh deploy

### 5. Attach a persistent volume

```bash
railway volume add
```

When prompted:
- **Mount path:** `/app/backend/data`
- **Size:** 1 GB is plenty for SQLite + ~hundreds of rendered runs

Without this volume the seen-store and post log reset on every deploy.

### 6. Set environment variables

```bash
railway variables --set CAROUSEL_LOG=INFO
railway variables --set CAROUSEL_PRUNE_DAYS=180
railway variables --set CAROUSEL_CACHE_DAYS=30
```

Optional integrations (skip the ones you don't use):

```bash
# LLM rewriter
railway variables --set LLM_API_KEY=sk-...
railway variables --set LLM_MODEL=gpt-4o-mini

# Telegram delivery
railway variables --set TELEGRAM_BOT_TOKEN=123:abc
railway variables --set CHAT_F1=-1001234567890
railway variables --set CHAT_NBA=-100...

# NewsAPI + image fallbacks
railway variables --set NEWSAPI_KEY=...
railway variables --set PEXELS_API_KEY=...
railway variables --set UNSPLASH_ACCESS_KEY=...
```

`PORT` is set by Railway automatically — don't override it.

### 7. Expose a public URL

```bash
railway domain
```

This generates a `*.up.railway.app` URL. Open it — you should land on
the Carousel Studio UI.

## Verifying the deploy

```bash
# Health check (used by Railway's healthcheck probe too)
curl https://YOUR-APP.up.railway.app/health

# Topics endpoint
curl https://YOUR-APP.up.railway.app/topics
```

## Local Docker test (optional)

Reproduce the Railway image on your machine before pushing:

```bash
docker build -t carousel-studio .
docker run --rm -p 8000:8000 -v $PWD/local-data:/app/backend/data carousel-studio
# Open http://localhost:8000
```

## Troubleshooting

- **Healthcheck failing.** Look at the deploy logs — most likely Pillow
  couldn't import (missing system lib). The Dockerfile already pins
  `libjpeg62-turbo`, `libpng16-16`, `libwebp7`, `libfreetype6`.
- **"No articles" everywhere.** Some publishers block IPs that look like
  cloud (Railway's egress range). Add `kind: newsapi` sources in
  `topic.yaml` as a fallback and set `NEWSAPI_KEY`.
- **Frontend shows but `/topics` is 502.** Volume mount path is wrong —
  re-check it's `/app/backend/data`, not `/data` or `/backend/data`.
- **`CAROUSEL_ALLOW_LOCAL` warning in logs.** The SSRF guard refused a
  private/loopback URL coming out of an RSS feed. That's working as
  intended; if a specific source is broken, the source itself is the
  problem.

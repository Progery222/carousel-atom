# Deploying Carousel Studio

Single-service deployment: one Docker image where FastAPI serves both the
API and the prebuilt frontend. No CORS, no two-service plumbing.

The app is hosted on a **self-hosted Linux server** (`atom@10.20.87.230`, a
private-LAN box) with **GitHub-push auto-deploy** via a self-hosted GitHub
Actions runner. (It was previously on Railway; that has been retired.)

## What's in the box

| File                          | Purpose                                                       |
|-------------------------------|---------------------------------------------------------------|
| `Dockerfile`                  | Multi-stage: Node builds frontend → Python runs uvicorn       |
| `docker-compose.yml`          | Server runtime: port map, `./data` volume, `.env`, healthcheck |
| `.github/workflows/deploy.yml`| Auto-deploy: push to `main` → rebuild + restart on the server |
| `.dockerignore`               | Keeps the build context small (no `.venv`, `node_modules`)    |
| `.gitignore`                  | Excludes `backend/data/`, `.env`, logs, build artifacts       |

The Python image installs Pillow's runtime deps (`libjpeg`, `libpng`,
`libwebp`, `libfreetype`) — required for the carousel renderer.

## Architecture

```
 push to main ─▶ GitHub
                   │ (self-hosted runner long-polls outbound;
                   │  GitHub can't reach the private LAN inbound)
                   ▼
   self-hosted runner on atom-server
     actions/checkout → rsync code to /home/atom/carousel-atom
     docker compose up -d --build  →  healthcheck /health  →  live
```

The server is on a private LAN (`10.20.87.230`), so deployment is **pulled by
the runner** (outbound only) rather than pushed from GitHub. A push to `main`
redeploys within seconds.

- **Live dir:** `/home/atom/carousel-atom` (code, synced by the workflow)
- **App URL:** `http://10.20.87.230:8088` (host `8088` → container `8000`)
- **Data:** `/home/atom/carousel-atom/data` → `/app/backend/data` (persistent)
- **Secrets:** `/home/atom/carousel-atom/.env` (never committed, never rsynced)

## Persistent storage

SQLite (`backend/data/factory.db`) and rendered runs (`backend/data/output/`)
must survive deploys. They live in the bind-mounted `./data` directory next to
`docker-compose.yml`, which the deploy workflow deliberately **excludes** from
its `rsync --delete`, so redeploys never touch the seen-store or rendered runs.

## First-time server setup

These steps were run once during the Railway → self-hosted migration. They are
recorded here so the deployment can be rebuilt from scratch.

### 1. Prerequisites on the server

Ubuntu 24.04, Docker + Docker Compose v2, and the `atom` user in the `docker`
group (so Docker runs without sudo). `git`, `rsync`, `curl` available.

### 2. Live directory, data, and env

```bash
mkdir -p /home/atom/carousel-atom/data
cd /home/atom/carousel-atom
# Pull code (public repo):
git clone --depth 1 https://github.com/Progery222/carousel-atom.git /tmp/carousel-src
rsync -a --exclude '.git' /tmp/carousel-src/ /home/atom/carousel-atom/ && rm -rf /tmp/carousel-src
# Create .env (see "Environment variables" below). Minimal:
cat > .env <<'EOF'
CAROUSEL_LOG=INFO
CAROUSEL_PRUNE_DAYS=180
PUBLIC_BASE_URL=http://10.20.87.230:8088
EOF
chmod 600 .env
```

### 3. First deploy

```bash
cd /home/atom/carousel-atom
docker compose up -d --build
curl -fsS http://localhost:8088/health   # -> {"ok": true, ...}
```

### 4. Self-hosted runner (auto-deploy)

The runner lives in `~/actions-runner-carousel`, registered to this repo with
the label `carousel`, and runs as a **user-level systemd service** (no sudo;
linger keeps it alive across reboots).

```bash
# Get a registration token (from a machine with `gh` authed to the repo):
gh api -X POST /repos/Progery222/carousel-atom/actions/runners/registration-token -q .token

# On the server:
mkdir -p ~/actions-runner-carousel && cd ~/actions-runner-carousel
curl -fsSL -o runner.tar.gz <latest actions-runner linux-x64 url>
tar xzf runner.tar.gz
./config.sh --url https://github.com/Progery222/carousel-atom \
            --token <TOKEN> --name atom-server-carousel \
            --labels carousel --unattended --replace

# Run as a user systemd service:
loginctl enable-linger atom
mkdir -p ~/.config/systemd/user
# (unit file gh-runner-carousel.service: ExecStart=.../run.sh, Restart=always)
systemctl --user daemon-reload
systemctl --user enable --now gh-runner-carousel
```

Once the runner is online, pushing `.github/workflows/deploy.yml` to `main`
triggers the first automated deploy.

## Day-to-day

- **Deploy:** just `git push` to `main`. The runner rebuilds and restarts the
  container, then healthchecks `/health`.
- **Watch a deploy:** `gh run watch` (or the Actions tab).
- **Manual redeploy:** `gh workflow run "Deploy to atom-server"` (or
  `cd /home/atom/carousel-atom && docker compose up -d --build` on the server).
- **Logs:** `docker compose -f /home/atom/carousel-atom/docker-compose.yml logs -f`
- **Runner status:** `systemctl --user status gh-runner-carousel`

## Environment variables

Set these in `/home/atom/carousel-atom/.env`. All are optional except where
noted — the app runs with none of them set (the public `/api/v1` stays
disabled until `CAROUSEL_API_KEYS` is set).

```bash
# Core
CAROUSEL_LOG=INFO
CAROUSEL_PRUNE_DAYS=180
CAROUSEL_CACHE_DAYS=30

# Public /api/v1 (set to enable it). `name:key` pairs label each key.
CAROUSEL_API_KEYS=partner_acme:<random-hex>
# Absolute slide URLs in /api/v1 responses
PUBLIC_BASE_URL=http://10.20.87.230:8088

# LLM caption rewriter
LLM_API_KEY=...
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini

# Telegram delivery
TELEGRAM_BOT_TOKEN=123:abc
CHAT_F1=-100...
CHAT_NBA=-100...

# NewsAPI + image-search fallbacks
NEWSAPI_KEY=...
PEXELS_API_KEY=...
UNSPLASH_ACCESS_KEY=...
```

After editing `.env`, apply it with `docker compose up -d` (re-creates the
container with the new environment).

## Verifying the deploy

```bash
# Health (used by the workflow's probe too)
curl -fsS http://10.20.87.230:8088/health

# Topics
curl http://10.20.87.230:8088/topics

# Public API (requires CAROUSEL_API_KEYS)
curl -H "X-API-Key: <your-key>" http://10.20.87.230:8088/api/v1/topics
```

The UI is at `http://10.20.87.230:8088/`, the API reference at `/api-docs`,
and Swagger UI at `/api/v1/docs`.

## Local Docker test (optional)

```bash
docker build -t carousel-studio .
docker run --rm -p 8000:8000 -v "$PWD/local-data:/app/backend/data" carousel-studio
# Open http://localhost:8000
```

## Troubleshooting

- **Healthcheck failing.** Check `docker compose logs` — most likely Pillow
  couldn't import a system lib. The Dockerfile pins `libjpeg62-turbo`,
  `libpng16-16`, `libwebp7`, `libfreetype6`.
- **Port already in use.** `8088` was chosen because `8000`/`8080` were taken
  on this host. Change the host side of `ports:` in `docker-compose.yml` if it
  clashes.
- **Deploy didn't fire.** Check the runner: `systemctl --user status
  gh-runner-carousel`, and that it shows online under the repo's
  Settings → Actions → Runners.
- **"No articles" everywhere.** Some publishers block datacenter IPs. Add
  `kind: newsapi` sources in `topic.yaml` and set `NEWSAPI_KEY`.

<!-- Generated: 2026-06-04 | Updated: 2026-06-04 -->

# carousel-atom (Carousel Studio)

## Purpose
Carousel Studio is a local Mac/Linux app that turns RSS / HTML / NewsAPI news feeds into ready-to-post TikTok / Instagram carousels. The user picks a **topic** and a **design** in the frontend; the backend pulls fresh news → enriches → filters → scores → renders PNG slides + caption; the user edits; then exports a ZIP (or delivers to Telegram). It is two services with a REST boundary between them, plus a public `/api/v1` surface for server-to-server use.

- `backend/` — FastAPI + Pillow rendering pipeline, port 8000
- `frontend/` — Vite + React 19 + Tailwind + TypeScript SPA, port 5173

## Key Files
| File | Description |
|------|-------------|
| `CLAUDE.md` | Primary guidance for AI agents — architecture deep-dive, conventions, env vars. Read this first. |
| `README.md` | Project overview, run instructions, topic.yaml schema, scheduling docs. |
| `HANDOFF.md` | End-user (macOS) setup guide: prerequisites, first-run, optional integrations. |
| `DEPLOY.md` | Railway deployment guide (Docker, persistent volume, env, healthcheck). |
| `ANALYSIS.md` | Russian-language technical audit: strengths, weaknesses, 38 improvement proposals. |
| `Makefile` | Targets: `backend`, `frontend`, `install`, `test`, `prune`, `help`. |
| `dev.sh` | Bash launcher — kills stale processes, sets up venv, installs deps, runs both servers, streams logs. |
| `Start Carousel Studio.command` | macOS user-facing entry point; executes `dev.sh` then opens the browser. |
| `Dockerfile` | Multi-stage: Node 20 builds the frontend → Python 3.11 runtime with Pillow system libs serves both. |
| `railway.toml` | Railway deploy config (Dockerfile builder, `/health` healthcheck, restart policy). |
| `.env.example` | Template for all optional integrations — copy to `.env`. |
| `.dockerignore` / `.gitignore` | Exclude caches, `.venv/`, `backend/data/`, `.env`, build output. |

## Subdirectories
| Directory | Purpose |
|-----------|---------|
| `backend/` | FastAPI service: news pipeline, designs, topics, REST API (see `backend/AGENTS.md`) |
| `frontend/` | React 19 + Vite SPA studio UI (see `frontend/AGENTS.md`) |
| `docs/` | REST API reference for the public `/api/v1` surface (see `docs/AGENTS.md`) |
| `preview/` | PNG reference screenshots of designs (no code, no AGENTS.md) |

## For AI Agents

### Working In This Directory
- This repo uses plain `pip`/`venv`, **not** `uv`, and has **no ruff config**. The global instruction to run `uv run ruff ...` does **not** apply here — see `CLAUDE.md`.
- Backend is Python ≥ 3.11 (`pyproject.toml`), but `api/` code deliberately targets 3.9-compatible pydantic typing (`Optional[X]`, not `X | None`).
- `dev.sh` deliberately skips `pip install -e .` and installs runtime deps directly; uvicorn is launched from `backend/` so `api`, `core`, `designs` import via cwd.
- Always ask before `git push`; never use `--force` or `--no-verify`; never `git add .` — stage specific files. Conventional commit style (`feat:`, `fix:`, `refactor:`).
- Never commit `.env`, credentials, or API keys.

### Testing Requirements
- Backend: `cd backend && pytest -q` (full suite) — see `backend/tests/AGENTS.md`.
- Frontend: no test suite. `npm run lint` (eslint) and `npm run build` (tsc + vite) are the only checks — see `frontend/AGENTS.md`.

### Common Patterns
- REST is the only boundary between the two services; the frontend's `src/api.ts` is the sole place that talks to the backend.
- Restart the backend to pick up newly added topics or designs.

## Dependencies

### External
- **Backend**: FastAPI, Uvicorn, Pillow, requests, BeautifulSoup4, feedparser, PyYAML, slowapi.
- **Frontend**: React 19, react-router-dom, Vite, Tailwind, TypeScript, jszip, file-saver.
- **Deploy**: Docker, Railway.

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->

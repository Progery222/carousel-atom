#!/usr/bin/env bash
# One-shot dev launcher. Robust against the usual snags: stale pip in a
# fresh venv, leftover uvicorn/vite from previous runs, missing
# node_modules. Streams both logs to the current terminal.
#
# Note: we deliberately skip `pip install -e .` — editable mode needs
# pip ≥ 21.3 for PEP 660. Instead we install the runtime deps directly
# and let Python pick up the source modules via cwd (`uvicorn` is
# launched from `backend/`, so `api`, `core`, `designs` are importable).

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"

DEPS=(
  'pillow>=10.0'
  'requests>=2.31'
  'beautifulsoup4>=4.12'
  'feedparser>=6.0'
  'pyyaml>=6.0'
  'pytz>=2024.1'
  'python-dotenv>=1.0'
  'fastapi>=0.110'
  'uvicorn[standard]>=0.29'
  'python-multipart>=0.0.9'
  # PEP 604 polyfill — pydantic v2 needs this to evaluate "X | Y" type
  # annotations at runtime on Python < 3.10. Cheap belt-and-suspenders
  # alongside the explicit Optional[X] use in api/server.py.
  'eval_type_backport;python_version<"3.10"'
)

echo "→ killing any old carousel processes…"
pkill -f "uvicorn api.server:app" 2>/dev/null || true
pkill -f "vite"                    2>/dev/null || true
sleep 1

# ── Backend ──────────────────────────────────────────────────────────────
cd "$BACKEND"
if [[ ! -d .venv ]]; then
  echo "→ creating backend venv…"
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

echo "→ upgrading pip / setuptools / wheel…"
python -m pip install --upgrade --quiet pip setuptools wheel || {
  echo "!! pip upgrade failed; check your network"; exit 1; }

echo "→ installing backend deps…"
python -m pip install --quiet "${DEPS[@]}" || {
  echo "!! backend deps install failed"; exit 1; }

echo "→ starting uvicorn on :8000…"
uvicorn api.server:app --reload --port 8000 \
  > "$ROOT/.backend.log" 2>&1 &
BACKEND_PID=$!

# Give the backend a moment so its startup log appears before the frontend's
sleep 2

# ── Frontend ─────────────────────────────────────────────────────────────
cd "$FRONTEND"
if [[ ! -d node_modules ]]; then
  echo "→ installing frontend deps…"
  npm install
fi
echo "→ starting vite on :5173…"
npm run dev > "$ROOT/.frontend.log" 2>&1 &
FRONTEND_PID=$!

# ── Wait + cleanup ───────────────────────────────────────────────────────
trap 'echo; echo "→ stopping…"; kill $BACKEND_PID $FRONTEND_PID 2>/dev/null || true; exit 0' INT TERM

echo
echo "Backend  PID $BACKEND_PID  → http://localhost:8000  (logs: .backend.log)"
echo "Frontend PID $FRONTEND_PID  → http://localhost:5173  (logs: .frontend.log)"
echo
echo "Open the studio:  http://localhost:5173"
echo "Tail logs:        tail -f .backend.log .frontend.log"
echo "Ctrl+C here stops both."
echo

# Stream both logs from the start
tail -f "$ROOT/.backend.log" "$ROOT/.frontend.log"

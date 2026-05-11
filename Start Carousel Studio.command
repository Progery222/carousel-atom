#!/usr/bin/env bash
# Double-clickable macOS launcher for Carousel Studio.
#
# Why .command? On macOS, files with the .command extension open in
# Terminal.app on double-click. The shebang line below is what Terminal
# actually runs. Keep this file on the project root so `dirname "$0"`
# resolves to the right place.
#
# What it does:
#   1. cd's to the project root (so dev.sh's relative paths work)
#   2. Concurrently waits for Vite to come up on :5173, then opens
#      http://localhost:5173 in the default browser
#   3. exec's into dev.sh which keeps streaming both logs to this window;
#      Ctrl+C in the terminal stops both servers cleanly

cd "$(dirname "$0")" || {
  echo "could not cd to script directory"
  read -r -p "press enter to close…"
  exit 1
}

# Background watcher: poll Vite for ~20s, open browser as soon as it's up.
(
  for _ in $(seq 1 40); do
    sleep 0.5
    if curl -s -o /dev/null --max-time 1 http://localhost:5173 2>/dev/null; then
      open http://localhost:5173
      exit 0
    fi
  done
) &

exec ./dev.sh

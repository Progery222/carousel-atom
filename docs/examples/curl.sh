#!/usr/bin/env bash
# Carousel Studio /api/v1 — curl cookbook. Needs `jq` for the pretty output.
#
#   BASE=https://your-app.example.com KEY=your-api-key ./curl.sh
set -euo pipefail

BASE="${BASE:-http://localhost:8000}"
KEY="${KEY:?set KEY=your-api-key}"
AUTH=(-H "X-API-Key: $KEY")
JSON=(-H "Content-Type: application/json")

echo "── health (no auth) ──"
curl -fsS "$BASE/api/v1/health" | jq

echo "── discovery ──"
curl -fsS "${AUTH[@]}" "$BASE/api/v1/topics"  | jq '.[].slug'
curl -fsS "${AUTH[@]}" "$BASE/api/v1/designs" | jq '.[].slug'

echo "── preview candidates (no render) ──"
curl -fsS "${AUTH[@]}" "$BASE/api/v1/preview/articles?topic=f1&limit=8" | jq '.candidates | length'

echo "── async render → poll → fetch ──"
JOB=$(curl -fsS "${AUTH[@]}" "${JSON[@]}" \
  -d '{"kind":"render","topic":"f1","design":"newsflash"}' \
  "$BASE/api/v1/jobs" | jq -r .job_id)
echo "job: $JOB"

until STATUS=$(curl -fsS "${AUTH[@]}" "$BASE/api/v1/jobs/$JOB" | jq -r .status); \
      [ "$STATUS" = succeeded ] || [ "$STATUS" = failed ]; do
  echo "  …$STATUS"; sleep 3
done
echo "final: $STATUS"

RUN=$(curl -fsS "${AUTH[@]}" "$BASE/api/v1/jobs/$JOB" | jq -r .result.run_id)
echo "run_id: $RUN"

echo "── re-fetch the run + download zip ──"
curl -fsS "${AUTH[@]}" "$BASE/api/v1/runs/$RUN" | jq '{caption, slides: (.slides | length)}'
curl -fsS "${AUTH[@]}" "$BASE/api/v1/export/$RUN.zip" -o "$RUN.zip"
echo "saved $RUN.zip"

echo "── sync render (alternative; blocks 10–40s, no \"kind\" field) ──"
curl -fsS --max-time 90 "${AUTH[@]}" "${JSON[@]}" \
  -d '{"topic":"f1","design":"newsflash"}' \
  "$BASE/api/v1/render" | jq '{run_id, slides: (.slides | length)}'

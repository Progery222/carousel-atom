#!/usr/bin/env bash
# Carousel Studio /api/v1 — curl cookbook. Needs `jq` for the pretty output.
#
# Every JSON response uses the envelope: {success, data, meta}.
# Pipe through `jq .data` (or `jq .data.<field>`) to reach the payload.
#
#   ADMIN_KEY=your-admin-key BASE=https://your-app.example.com ./curl.sh
set -euo pipefail

BASE="${BASE:-http://localhost:8000}"
ADMIN_KEY="${ADMIN_KEY:?set ADMIN_KEY=your-admin-api-key}"
AUTH=(-H "X-API-Key: $ADMIN_KEY")
JSON=(-H "Content-Type: application/json")

echo "── service meta (no auth) ──"
curl -fsS "$BASE/api/v1/meta" | jq .data

echo "── create a scoped read+write key (admin) ──"
KEY=$(curl -fsS "${AUTH[@]}" "${JSON[@]}" \
  -d '{"name":"example_consumer","scopes":["read","write"]}' \
  "$BASE/api/v1/api-keys" | jq -r .data.key)
echo "new key: $KEY"

RAUTH=(-H "X-API-Key: $KEY")

echo "── discovery ──"
curl -fsS "${RAUTH[@]}" "$BASE/api/v1/topics"  | jq '.data[].slug'
curl -fsS "${RAUTH[@]}" "$BASE/api/v1/designs" | jq '.data[].slug'

echo "── preview candidates (no render) ──"
curl -fsS "${RAUTH[@]}" "${JSON[@]}" \
  -d '{"topic":"f1","limit":8}' \
  "$BASE/api/v1/actions/preview" | jq '.data.candidates | length'

echo "── async render → poll → fetch ──"
JOB=$(curl -fsS "${RAUTH[@]}" "${JSON[@]}" \
  -d '{"kind":"render","topic":"f1","design":"newsflash"}' \
  "$BASE/api/v1/jobs" | jq -r .data.job_id)
echo "job: $JOB"

until STATUS=$(curl -fsS "${RAUTH[@]}" "$BASE/api/v1/jobs/$JOB" | jq -r .data.status); \
      [ "$STATUS" = succeeded ] || [ "$STATUS" = failed ]; do
  echo "  ...$STATUS"; sleep 3
done
echo "final: $STATUS"

RUN=$(curl -fsS "${RAUTH[@]}" "$BASE/api/v1/jobs/$JOB" | jq -r .data.result.run_id)
echo "run_id: $RUN"

echo "── re-fetch the run ──"
curl -fsS "${RAUTH[@]}" "$BASE/api/v1/runs/$RUN" \
  | jq '{caption: .data.caption, slides: (.data.slides | length)}'

echo "── download zip ──"
curl -fsS "${RAUTH[@]}" "$BASE/api/v1/runs/$RUN/export" -o "$RUN.zip"
echo "saved $RUN.zip"

echo "── list runs (cursor-paginated) ──"
PAGE=$(curl -fsS "${RAUTH[@]}" "$BASE/api/v1/runs?limit=5")
echo "$PAGE" | jq '{count: (.data.items | length), next_cursor: .data.next_cursor}'

echo "── sync render (alternative; blocks 10-40s) ──"
curl -fsS --max-time 90 "${RAUTH[@]}" "${JSON[@]}" \
  -d '{"topic":"f1","design":"newsflash"}' \
  "$BASE/api/v1/actions/render" | jq '{run_id: .data.run_id, slides: (.data.slides | length)}'

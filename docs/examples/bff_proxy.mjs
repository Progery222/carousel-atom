// Backend-for-Frontend (BFF) proxy — Node 18+ (built-in fetch, no deps).
//
// Why: a browser app must NEVER hold the Carousel API key. Run this small
// server-side proxy that keeps the key secret and forwards a safe subset of
// the API to your frontend. Your browser code talks to THIS server, not to
// Carousel directly (see browser.ts).
//
//   CAROUSEL_BASE=https://your-app.example.com \
//   CAROUSEL_KEY=your-api-key \
//   node bff_proxy.mjs            # listens on :8787
//
// Add your own auth/session checks before proxying in production.

import http from "node:http";

const BASE = (process.env.CAROUSEL_BASE || "http://localhost:8000").replace(/\/$/, "");
const KEY = process.env.CAROUSEL_KEY || "";
const PORT = Number(process.env.PORT || 8787);

// Only allow the endpoints your frontend actually needs.
const ALLOW = [
  { method: "GET", re: /^\/api\/v1\/topics$/ },
  { method: "GET", re: /^\/api\/v1\/designs$/ },
  { method: "POST", re: /^\/api\/v1\/jobs$/ },
  { method: "GET", re: /^\/api\/v1\/jobs\/[\w-]+$/ },
  { method: "GET", re: /^\/api\/v1\/runs\/[\w.-]+$/ },
];

function allowed(method, path) {
  return ALLOW.some((a) => a.method === method && a.re.test(path));
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, "http://localhost");
  if (!allowed(req.method, url.pathname)) {
    res.writeHead(403, { "content-type": "application/json" });
    return res.end(JSON.stringify({ error: { code: "forbidden", message: "not proxied" } }));
  }

  // TODO: authenticate the browser user / session here before proxying.

  const chunks = [];
  for await (const c of req) chunks.push(c);
  const body = chunks.length ? Buffer.concat(chunks) : undefined;

  const upstream = await fetch(`${BASE}${url.pathname}${url.search}`, {
    method: req.method,
    headers: { "X-API-Key": KEY, "content-type": "application/json" },
    body: req.method === "GET" || req.method === "HEAD" ? undefined : body,
  });

  const text = await upstream.text();
  res.writeHead(upstream.status, { "content-type": "application/json" });
  res.end(text);
});

server.listen(PORT, () => console.log(`BFF proxy on :${PORT} → ${BASE}`));

import { Link } from "react-router-dom";
import { API_BASE } from "../api";

/** Endpoint reference data — single source of truth for the docs page. */
interface EndpointDoc {
  method: "GET" | "POST" | "DELETE";
  path: string;
  summary: string;
  description: string;
  status?: string; // success status code shown on the card (e.g. "202")
  scope: "none" | "read" | "write" | "admin";
  query?: { name: string; type: string; required: boolean; desc: string }[];
  body?: string; // JSON example
  response: string; // JSON example (always shows envelope)
  rateLimit: "heavy" | "light" | "none";
}

const RENDER_OUT = `{
  "success": true,
  "data": {
    "status": "ok",
    "run_id": "f1_newsflash_1715000000_a1b2c3",
    "topic": "f1",
    "design": "newsflash",
    "caption": "F1 News · Verstappen wins Monaco...",
    "articles": [
      { "title": "...", "url": "...", "source": "...",
        "image_url": "...", "description": "..." }
    ],
    "slides": [
      { "index": 0, "url": "https://your-app.example.com/output/f1/.../slide_0.png" }
    ],
    "diagnostics": { "raw": 87, "fresh": 42, "after_enrich": 18 }
  },
  "meta": { "request_id": "ab12cd34" }
}`;

const ENDPOINTS: EndpointDoc[] = [
  // ── System ──────────────────────────────────────────────────────────────
  {
    method: "GET",
    path: "/api/v1/health",
    summary: "Liveness ping (no auth)",
    description:
      "Always returns ok. No X-API-Key required. Use it for uptime monitoring without burning your rate-limit budget.",
    scope: "none",
    response: `{
  "success": true,
  "data": { "status": "ok", "version": "0.1.0" },
  "meta": { "request_id": "ab12cd34" }
}`,
    rateLimit: "none",
  },
  {
    method: "GET",
    path: "/api/v1/meta",
    summary: "Service metadata / capability descriptor (no auth)",
    description:
      "Machine-readable contract: service name, API version, available resources and actions, supported scopes, pagination style, auth scheme. A central orchestrator reads this to learn what the service exposes.",
    scope: "none",
    response: `{
  "success": true,
  "data": {
    "service": "carousel-studio",
    "version": "0.1.0",
    "api_version": "v1",
    "capabilities": {
      "resources": ["topics", "designs", "runs", "jobs", "api-keys"],
      "actions": ["render", "render-edit", "render-partial", "preview"]
    },
    "scopes": ["read", "write", "admin"],
    "pagination": { "style": "cursor", "limit_param": "limit",
                    "cursor_param": "cursor", "default_limit": 20, "max_limit": 100 },
    "auth": { "type": "apiKey", "in": "header", "name": "X-API-Key" }
  },
  "meta": { "request_id": "ab12cd34" }
}`,
    rateLimit: "light",
  },
  {
    method: "GET",
    path: "/api/v1/auth/verify",
    summary: "Verify the calling API key",
    description:
      "Returns the key_id, name, and scopes of the key used to authenticate this request. Useful for confirming a key is valid and checking what it can do.",
    scope: "read",
    response: `{
  "success": true,
  "data": { "key_id": "k_abc123", "name": "partner_acme", "scopes": ["read", "write"] },
  "meta": { "request_id": "ab12cd34" }
}`,
    rateLimit: "light",
  },
  // ── Discovery ────────────────────────────────────────────────────────────
  {
    method: "GET",
    path: "/api/v1/topics",
    summary: "List available topics",
    description:
      "Every topic configured in backend/topics/. Use the slug field for render actions and job requests.",
    scope: "read",
    response: `{
  "success": true,
  "data": [
    { "slug": "f1", "name": "F1 Daily", "source_count": 8, "news_per_carousel": 5 }
  ],
  "meta": { "request_id": "ab12cd34" }
}`,
    rateLimit: "light",
  },
  {
    method: "GET",
    path: "/api/v1/topics/{slug}",
    summary: "Get a single topic",
    description: "Returns the topic config for one slug. 404 if unknown.",
    scope: "read",
    response: `{
  "success": true,
  "data": { "slug": "f1", "name": "F1 Daily", "source_count": 8, "news_per_carousel": 5 },
  "meta": { "request_id": "ab12cd34" }
}`,
    rateLimit: "light",
  },
  {
    method: "GET",
    path: "/api/v1/designs",
    summary: "List available designs",
    description:
      "Every design template registered in backend/designs/__init__.py. Use the slug field for render actions.",
    scope: "read",
    response: `{
  "success": true,
  "data": [
    { "slug": "newsflash", "name": "Newsflash",
      "description": "Hero photo + bold headline on a brand-colored card." }
  ],
  "meta": { "request_id": "ab12cd34" }
}`,
    rateLimit: "light",
  },
  {
    method: "GET",
    path: "/api/v1/designs/{slug}",
    summary: "Get a single design",
    description: "Returns the design metadata for one slug. 404 if unknown.",
    scope: "read",
    response: `{
  "success": true,
  "data": { "slug": "newsflash", "name": "Newsflash",
            "description": "Hero photo + bold headline on a brand-colored card." },
  "meta": { "request_id": "ab12cd34" }
}`,
    rateLimit: "light",
  },
  // ── Actions ──────────────────────────────────────────────────────────────
  {
    method: "POST",
    path: "/api/v1/actions/render",
    summary: "Render a fresh carousel (sync)",
    description:
      "Pull fresh news for the topic, score + dedupe, render slides with the chosen design, generate a caption. Returns absolute slide URLs. Synchronous — blocks 10–40s. For anything user-facing or behind a proxy, prefer POST /api/v1/jobs (async). An unknown topic/design returns 404 before any work starts; oversized bodies return 422.",
    scope: "write",
    body: `{
  "topic": "f1",
  "design": "newsflash",
  "mark_seen": true,
  "cross_topic_dedup": false,
  "deliver": ""
}`,
    response: RENDER_OUT,
    rateLimit: "heavy",
  },
  {
    method: "POST",
    path: "/api/v1/actions/render-edit",
    summary: "Re-render with user-edited articles",
    description:
      "Skip the network fetch — supply your own article list (e.g. user-edited titles, swapped image URLs) and render slides from them. mark_seen is always false on this route.",
    scope: "write",
    body: `{
  "topic": "f1",
  "design": "newsflash",
  "articles": [
    { "title": "...", "url": "...", "source": "...",
      "image_url": "...", "description": "..." }
  ]
}`,
    response: RENDER_OUT,
    rateLimit: "heavy",
  },
  {
    method: "POST",
    path: "/api/v1/actions/render-partial",
    summary: "Per-slot re-roll render",
    description:
      "Mix locked and re-rolled slots. Items that are null get a fresh story from the pipeline; non-null items are kept verbatim.",
    scope: "write",
    body: `{
  "topic": "f1",
  "design": "newsflash",
  "articles": [
    { "title": "Locked slide 1", "url": "...", "source": "...", "image_url": "..." },
    null,
    null
  ]
}`,
    response: RENDER_OUT,
    rateLimit: "heavy",
  },
  {
    method: "POST",
    path: "/api/v1/actions/preview",
    summary: "Preview fresh article candidates (no render)",
    description:
      "Runs the news fetch + freshness + scoring pipeline without rendering slides. Use this to pre-flight a carousel — show candidate stories and let the user pick.",
    scope: "read",
    body: `{ "topic": "f1", "limit": 12 }`,
    response: `{
  "success": true,
  "data": {
    "topic": "f1",
    "raw": 87,
    "fresh": 42,
    "enriched": 18,
    "candidates": [
      { "title": "Verstappen wins Monaco GP", "url": "https://...",
        "source": "f1.com", "image_url": "https://...",
        "description": "...", "score": 4.7 }
    ]
  },
  "meta": { "request_id": "ab12cd34" }
}`,
    rateLimit: "light",
  },
  // ── Runs ─────────────────────────────────────────────────────────────────
  {
    method: "GET",
    path: "/api/v1/runs",
    summary: "List rendered runs (cursor-paginated)",
    description:
      "Returns a cursor-paginated list of rendered runs. Newest first. Use ?limit= (1–100, default 20) and ?cursor= for subsequent pages.",
    scope: "read",
    query: [
      { name: "limit", type: "int", required: false, desc: "Page size 1–100 (default 20)" },
      { name: "cursor", type: "string", required: false, desc: "Opaque cursor from previous page" },
    ],
    response: `{
  "success": true,
  "data": {
    "items": [
      { "run_id": "f1_newsflash_1715000000_a1b2c3", "topic": "f1",
        "design": "newsflash", "created_at": 1715000000,
        "slide_count": 5, "caption": "F1 News · ..." }
    ],
    "next_cursor": "eyJ0IjoxNzE1MDAwMDAwfQ"
  },
  "meta": { "request_id": "ab12cd34" }
}`,
    rateLimit: "light",
  },
  {
    method: "GET",
    path: "/api/v1/runs/{run_id}",
    summary: "Fetch a previously rendered run",
    description:
      "Reconstruct a previously rendered run from disk: caption, articles, and absolute slide URLs. Durable counterpart to a job — stays readable across restarts and after the job is evicted. Pass ?topic= if the slug can't be recovered from run_id.",
    scope: "read",
    query: [
      { name: "topic", type: "string", required: false, desc: "Topic slug (only if run_id parsing is ambiguous)" },
    ],
    response: RENDER_OUT,
    rateLimit: "light",
  },
  {
    method: "GET",
    path: "/api/v1/runs/{run_id}/export",
    summary: "Download a run as a ZIP (binary)",
    description:
      "Returns a ZIP containing slide_*.png, caption.txt, and metadata.json. Binary — not JSON-enveloped. Pass ?topic= if the slug can't be recovered from run_id.",
    scope: "read",
    query: [
      { name: "topic", type: "string", required: false, desc: "Topic slug (only if run_id parsing is ambiguous)" },
    ],
    response: `<binary application/zip>
Content-Disposition: attachment; filename="<run_id>.zip"`,
    rateLimit: "heavy",
  },
  {
    method: "DELETE",
    path: "/api/v1/runs/{run_id}",
    summary: "Delete a rendered run",
    description:
      "Removes the run from the seen-store and deletes its slide files from disk. 404 if the run_id is unknown.",
    scope: "write",
    response: `{
  "success": true,
  "data": { "run_id": "f1_newsflash_1715000000_a1b2c3", "deleted": true },
  "meta": { "request_id": "ab12cd34" }
}`,
    rateLimit: "light",
  },
  // ── Async jobs ───────────────────────────────────────────────────────────
  {
    method: "POST",
    path: "/api/v1/jobs",
    summary: "Submit an async render job",
    status: "202",
    description:
      "Enqueue a render and return immediately with a job_id. Poll GET /api/v1/jobs/{job_id} or pass a webhook_url (https-only, SSRF-guarded) to be notified on completion. Body mirrors the sync render endpoints, tagged with kind: render | render_edit | render_partial.",
    scope: "write",
    body: `{
  "kind": "render",
  "topic": "f1",
  "design": "newsflash",
  "webhook_url": "https://my-service.example.com/carousel/done"
}`,
    response: `// 202 Accepted
{
  "success": true,
  "data": {
    "job_id": "9f1c2a...",
    "kind": "render",
    "status": "queued",
    "created_at": 1715000000,
    "started_at": null,
    "finished_at": null,
    "status_url": "https://your-app.example.com/api/v1/jobs/9f1c2a...",
    "result": null,
    "error": null
  },
  "meta": { "request_id": "ab12cd34" }
}`,
    rateLimit: "heavy",
  },
  {
    method: "GET",
    path: "/api/v1/jobs",
    summary: "List async jobs (cursor-paginated)",
    description:
      "Returns a cursor-paginated snapshot of in-memory jobs. Newest first. Use ?limit= and ?cursor= for paging.",
    scope: "read",
    query: [
      { name: "limit", type: "int", required: false, desc: "Page size 1–100 (default 20)" },
      { name: "cursor", type: "string", required: false, desc: "Opaque cursor from previous page" },
    ],
    response: `{
  "success": true,
  "data": {
    "items": [ { "job_id": "9f1c2a...", "kind": "render", "status": "succeeded", ... } ],
    "next_cursor": null
  },
  "meta": { "request_id": "ab12cd34" }
}`,
    rateLimit: "light",
  },
  {
    method: "GET",
    path: "/api/v1/jobs/{job_id}",
    summary: "Get async job status & result",
    description:
      "Poll for the job state: queued → running → succeeded | failed. On success, result holds the full RenderOut; on failure, error holds {code, message, details}. A job_id is ephemeral (in-memory, single-instance) — it 404s after a ~1h TTL or a restart. The durable handle is result.run_id (see GET /runs/{run_id}).",
    scope: "read",
    response: `{
  "success": true,
  "data": {
    "job_id": "9f1c2a...",
    "kind": "render",
    "status": "succeeded",
    "created_at": 1715000000,
    "started_at": 1715000001,
    "finished_at": 1715000034,
    "status_url": "https://your-app.example.com/api/v1/jobs/9f1c2a...",
    "result": { "status": "ok", "run_id": "f1_newsflash_...",
                "caption": "...", "slides": [ "..." ], "articles": [ "..." ] },
    "error": null
  },
  "meta": { "request_id": "ab12cd34" }
}`,
    rateLimit: "light",
  },
  // ── API key management (admin) ────────────────────────────────────────────
  {
    method: "POST",
    path: "/api/v1/api-keys",
    summary: "Create an API key (raw secret shown once)",
    status: "201",
    description:
      "Create a new scoped key. scopes must be a subset of read/write/admin. The raw csk_... secret is returned once and never stored — only its hash is kept.",
    scope: "admin",
    body: `{ "name": "partner_acme", "scopes": ["read", "write"] }`,
    response: `{
  "success": true,
  "data": {
    "key_id": "k_abc123",
    "key": "csk_0a1b2c3d4e5f...",
    "key_prefix": "csk_0a1b",
    "name": "partner_acme",
    "scopes": ["read", "write"],
    "created_at": "2024-05-06T14:00:00Z"
  },
  "meta": { "request_id": "ab12cd34" }
}`,
    rateLimit: "light",
  },
  {
    method: "GET",
    path: "/api/v1/api-keys",
    summary: "List API keys (no raw secrets)",
    description:
      "Returns all active keys with metadata. Raw secrets are never included in list responses.",
    scope: "admin",
    response: `{
  "success": true,
  "data": [
    { "key_id": "k_abc123", "key_prefix": "csk_0a1b",
      "name": "partner_acme", "scopes": ["read", "write"],
      "created_at": "2024-05-06T14:00:00Z" }
  ],
  "meta": { "request_id": "ab12cd34" }
}`,
    rateLimit: "light",
  },
  {
    method: "GET",
    path: "/api/v1/api-keys/{key_id}",
    summary: "Get a single API key",
    description: "Returns metadata for one key. 404 if unknown.",
    scope: "admin",
    response: `{
  "success": true,
  "data": { "key_id": "k_abc123", "key_prefix": "csk_0a1b",
            "name": "partner_acme", "scopes": ["read", "write"],
            "created_at": "2024-05-06T14:00:00Z" },
  "meta": { "request_id": "ab12cd34" }
}`,
    rateLimit: "light",
  },
  {
    method: "DELETE",
    path: "/api/v1/api-keys/{key_id}",
    summary: "Revoke an API key",
    description:
      "Permanently revokes a key. Immediately rejects all future requests using it. 404 if unknown.",
    scope: "admin",
    response: `{
  "success": true,
  "data": { "key_id": "k_abc123", "revoked": true },
  "meta": { "request_id": "ab12cd34" }
}`,
    rateLimit: "light",
  },
];

const ERROR_CODES: { code: number; key: string; meaning: string }[] = [
  { code: 401, key: "unauthorized", meaning: "Missing or invalid X-API-Key." },
  { code: 403, key: "forbidden", meaning: "Key lacks the required scope (read/write/admin)." },
  { code: 422, key: "validation_error", meaning: "Body or params failed validation. See details for per-field errors." },
  { code: 404, key: "not_found", meaning: "Unknown topic, design, run, job, or API key." },
  { code: 409, key: "conflict", meaning: "Operation can't complete (e.g. no usable articles — see details for pipeline diagnostics)." },
  { code: 429, key: "rate_limited", meaning: "Per-key rate limit hit. See Retry-After header." },
  { code: 500, key: "internal_error", meaning: "Unexpected server error. Details in server logs." },
];

const SCOPE_COLOR: Record<string, string> = {
  none: "bg-ink-600/50 text-ink-300",
  read: "bg-sky-500/15 text-sky-400",
  write: "bg-emerald-500/15 text-emerald-400",
  admin: "bg-violet-500/15 text-violet-400",
};

function CodeBlock({ children, lang }: { children: string; lang?: string }) {
  return (
    <pre className="bg-ink-800 border border-ink-700/40 rounded-xl p-4 overflow-x-auto text-xs leading-relaxed text-ink-100">
      {lang && (
        <div className="text-[10px] uppercase tracking-wider text-ink-400 mb-2">{lang}</div>
      )}
      <code>{children}</code>
    </pre>
  );
}

function Section({
  id,
  title,
  children,
}: {
  id: string;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section id={id} className="scroll-mt-20 mb-12">
      <h2 className="text-2xl font-bold text-ink-100 mb-4 flex items-baseline gap-3">
        {title}
        <a href={`#${id}`} className="text-ink-400 hover:text-accent text-base">#</a>
      </h2>
      <div className="space-y-4 text-sm text-ink-200">{children}</div>
    </section>
  );
}

function EndpointCard({ ep }: { ep: EndpointDoc }) {
  const id = ep.path.replace(/[{}/]/g, "-").replace(/-+/g, "-").replace(/^-|-$/g, "");
  const methodColor =
    ep.method === "GET"
      ? "bg-accent/15 text-accent"
      : ep.method === "DELETE"
        ? "bg-red-500/15 text-red-400"
        : "bg-emerald-500/15 text-emerald-400";
  return (
    <article id={id} className="scroll-mt-20 mb-8 border border-ink-700/40 rounded-2xl p-5 bg-ink-800/40">
      <header className="flex flex-wrap items-baseline gap-3 mb-3">
        <span className={`px-2 py-0.5 text-[10px] font-bold rounded ${methodColor}`}>
          {ep.method}
        </span>
        <code className="font-mono text-sm text-ink-100">{ep.path}</code>
        {ep.status && (
          <span className="px-1.5 py-0.5 text-[10px] font-bold rounded bg-amber-500/15 text-amber-400">
            {ep.status}
          </span>
        )}
        <span className={`px-1.5 py-0.5 text-[10px] font-bold rounded ${SCOPE_COLOR[ep.scope]}`}>
          {ep.scope === "none" ? "no auth" : ep.scope}
        </span>
        <span className="text-[10px] uppercase tracking-wider text-ink-400 ml-auto">
          {ep.rateLimit === "heavy"
            ? "Heavy tier"
            : ep.rateLimit === "light"
              ? "Light tier"
              : "No auth"}
        </span>
      </header>
      <p className="text-sm text-ink-200 font-medium mb-1">{ep.summary}</p>
      <p className="text-xs text-ink-300 mb-4">{ep.description}</p>
      {ep.query && (
        <div className="mb-3">
          <h4 className="text-[10px] uppercase tracking-wider text-ink-400 mb-1">Query parameters</h4>
          <table className="w-full text-xs">
            <tbody>
              {ep.query.map((q) => (
                <tr key={q.name} className="border-t border-ink-700/40">
                  <td className="py-1.5 pr-3 font-mono text-ink-100 w-32">{q.name}</td>
                  <td className="py-1.5 pr-3 text-ink-300">{q.type}{q.required ? " · required" : ""}</td>
                  <td className="py-1.5 text-ink-300">{q.desc}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {ep.body && (
        <div className="mb-3">
          <h4 className="text-[10px] uppercase tracking-wider text-ink-400 mb-1">Request body</h4>
          <CodeBlock lang="json">{ep.body}</CodeBlock>
        </div>
      )}
      <div>
        <h4 className="text-[10px] uppercase tracking-wider text-ink-400 mb-1">Response</h4>
        <CodeBlock lang="json">{ep.response}</CodeBlock>
      </div>
    </article>
  );
}

export default function ApiDocsPage() {
  const swaggerHref = `${API_BASE}/api/v1/docs`;
  const openapiHref = `${API_BASE}/api/v1/openapi.json`;
  const redocHref = `${API_BASE}/api/v1/redoc`;
  const repoHref = "https://github.com/Progery222/carousel-atom";
  const examplesHref = `${repoHref}/tree/main/docs/examples`;

  return (
    <div className="min-h-screen bg-ink-900 text-ink-100">
      <header className="border-b border-ink-700/40 bg-ink-800/60 backdrop-blur sticky top-0 z-10">
        <div className="max-w-5xl mx-auto px-8 py-4 flex items-center gap-4">
          <Link
            to="/"
            className="inline-flex items-center justify-center w-9 h-9 rounded-xl bg-accent text-white font-bold shadow-soft"
          >
            C
          </Link>
          <div className="flex-1">
            <div className="text-sm font-bold text-ink-100">Carousel Studio API</div>
            <div className="text-[11px] text-ink-300">Cross-service standard /api/v1 reference</div>
          </div>
          <Link
            to="/"
            className="px-3 py-1.5 text-xs font-medium text-ink-300 hover:text-accent rounded-lg hover:bg-ink-700 transition"
          >
            ← Back to Studio
          </Link>
        </div>
      </header>

      <div className="max-w-5xl mx-auto px-8 py-10 grid grid-cols-1 lg:grid-cols-[1fr_220px] gap-12">
        <main>
          <h1 className="text-4xl font-bold mb-3">Carousel Studio API</h1>
          <p className="text-ink-300 mb-6 max-w-2xl">
            A cross-service standard REST API: every service a central orchestrator
            connects to uses the same <code className="text-accent">X-API-Key</code> header,
            the same response envelope, the same error-code set, cursor pagination, and
            scoped keys. Generates TikTok / Instagram-ready news carousels — sync or async
            — and returns PNG slides + a caption ready to post.
            Building a browser app? Front it with a BFF —{" "}
            <a href="#browser-key-safety" className="text-accent hover:underline">
              never ship the key to the browser
            </a>
            .
          </p>
          <div className="flex flex-wrap gap-3 mb-10">
            <a
              href={swaggerHref}
              target="_blank"
              rel="noopener noreferrer"
              className="px-4 py-2 bg-accent text-white text-sm font-medium rounded-lg shadow-soft hover:shadow-card transition"
            >
              Open Swagger UI ↗
            </a>
            <a
              href={redocHref}
              target="_blank"
              rel="noopener noreferrer"
              className="px-4 py-2 bg-ink-800 text-ink-100 text-sm font-medium rounded-lg hover:bg-ink-700 transition"
            >
              ReDoc ↗
            </a>
            <a
              href={openapiHref}
              target="_blank"
              rel="noopener noreferrer"
              className="px-4 py-2 bg-ink-800 text-ink-100 text-sm font-medium rounded-lg hover:bg-ink-700 transition"
            >
              openapi.json ↗
            </a>
          </div>

          {/* ── Response envelope ─────────────────────────────────────────── */}
          <Section id="response-envelope" title="Response envelope">
            <p>
              Every JSON response uses one shape. A central service can pattern-match on{" "}
              <code className="text-accent">success</code> and branch on{" "}
              <code className="text-accent">data</code> vs{" "}
              <code className="text-accent">error</code> without endpoint-specific parsing.
            </p>
            <p className="text-xs font-semibold text-ink-300 uppercase tracking-wider">Success</p>
            <CodeBlock lang="json">{`{
  "success": true,
  "data": <payload>,
  "meta": { "request_id": "ab12cd34" }
}`}</CodeBlock>
            <p className="text-xs font-semibold text-ink-300 uppercase tracking-wider">Error</p>
            <CodeBlock lang="json">{`{
  "success": false,
  "error": {
    "code": "not_found",
    "message": "run not found: f1_newsflash_xxx",
    "details": {}
  },
  "meta": { "request_id": "ab12cd34" }
}`}</CodeBlock>
            <p className="text-xs text-ink-400">
              <code>details</code> is optional — present for{" "}
              <code>validation_error</code> (per-field errors) and{" "}
              <code>conflict</code> (pipeline diagnostics). Binary downloads (ZIP export)
              are the only non-JSON responses.
            </p>
            <p>
              Send an <code className="text-accent">X-Request-ID</code> header to have
              it echoed back in <code>meta.request_id</code> and used in server logs.
            </p>
          </Section>

          {/* ── Authentication & scopes ───────────────────────────────────── */}
          <Section id="authentication" title="Authentication &amp; scopes">
            <p>
              Send <code className="text-accent">X-API-Key</code> on every request except
              the public system endpoints (<code>/health</code>, <code>/meta</code>,{" "}
              <code>/openapi.json</code>). Two kinds of keys:
            </p>
            <ul className="list-disc list-inside text-ink-300 space-y-1">
              <li>
                <strong className="text-ink-100">Bootstrap keys</strong> — set via{" "}
                <code>CAROUSEL_API_KEYS=name:key,...</code> in the environment. Full{" "}
                <strong>admin</strong> scope. Use these to mint scoped consumer keys.
              </li>
              <li>
                <strong className="text-ink-100">Scoped keys</strong> — created via{" "}
                <code>POST /api/v1/api-keys</code>, stored{" "}
                <strong>hashed</strong> (raw secret shown once at creation).
              </li>
            </ul>
            <p>
              Scopes are hierarchical: <strong>admin</strong> &sup; <strong>write</strong>{" "}
              &sup; <strong>read</strong>.
            </p>
            <table className="w-full text-xs border-collapse">
              <thead>
                <tr className="text-left border-b border-ink-700/60">
                  <th className="py-2 pr-4 font-semibold text-ink-100">Scope</th>
                  <th className="py-2 font-semibold text-ink-100">Grants</th>
                </tr>
              </thead>
              <tbody>
                <tr className="border-b border-ink-700/30">
                  <td className="py-2 pr-4 font-mono text-sky-400">read</td>
                  <td className="py-2 text-ink-300">discovery, runs, jobs, preview, auth/verify</td>
                </tr>
                <tr className="border-b border-ink-700/30">
                  <td className="py-2 pr-4 font-mono text-emerald-400">write</td>
                  <td className="py-2 text-ink-300">everything read + render actions, create jobs, delete runs</td>
                </tr>
                <tr className="border-b border-ink-700/30">
                  <td className="py-2 pr-4 font-mono text-violet-400">admin</td>
                  <td className="py-2 text-ink-300">everything write + manage API keys</td>
                </tr>
              </tbody>
            </table>
            <p className="text-xs text-ink-400">
              A missing/unknown key returns a generic <strong>401</strong> (no disclosure
              of whether the instance is provisioned). Insufficient scope returns{" "}
              <strong>403</strong>.
            </p>
          </Section>

          {/* ── Pagination ───────────────────────────────────────────────── */}
          <Section id="pagination" title="Pagination">
            <p>
              List endpoints (<code className="text-accent">GET /runs</code>,{" "}
              <code className="text-accent">GET /jobs</code>) use{" "}
              <strong>cursor pagination</strong>. The cursor is an opaque token; do not
              parse or construct it.
            </p>
            <CodeBlock lang="bash">{`GET /api/v1/runs?limit=20&cursor=<opaque>`}</CodeBlock>
            <ul className="list-disc list-inside text-ink-300 space-y-1">
              <li><code>limit</code> — 1..100 (default 20)</li>
              <li><code>cursor</code> — omit for the first page; use <code>data.next_cursor</code> from the previous response</li>
              <li>Loop until <code>data.next_cursor</code> is <code>null</code></li>
              <li>A malformed cursor returns <code>422 validation_error</code></li>
            </ul>
          </Section>

          {/* ── Quickstart ───────────────────────────────────────────────── */}
          <Section id="quickstart" title="Quickstart">
            <p>
              Recommended flow: submit an <strong>async job</strong>, poll until it
              finishes, then read the slides from <code>.data.result</code>. (A render
              takes 10–40s, so a long-held sync request can hit proxy/Funnel timeouts.)
              Ready-to-run clients live in{" "}
              <a
                href={examplesHref}
                target="_blank"
                rel="noopener noreferrer"
                className="text-accent hover:underline"
              >
                docs/examples/
              </a>{" "}
              (Python, curl, Node BFF, browser, webhook receiver).
            </p>
            <CodeBlock lang="bash">{`BASE="https://your-app.example.com/api/v1"; KEY="your-key"

# Discover (no auth)
curl -s "$BASE/meta" | jq .data.capabilities

# Render async (recommended)
JOB=$(curl -s -H "X-API-Key: $KEY" -H "Content-Type: application/json" \\
  -d '{"kind":"render","topic":"f1","design":"newsflash"}' \\
  "$BASE/jobs" | jq -r .data.job_id)

# Poll — read response from .data
curl -s -H "X-API-Key: $KEY" "$BASE/jobs/$JOB" | jq .data.status

# Or render synchronously
curl -s -H "X-API-Key: $KEY" -H "Content-Type: application/json" \\
  -d '{"topic":"f1","design":"newsflash"}' "$BASE/actions/render" | jq .data.run_id

# List runs (cursor-paginated) — page data under .data.items
curl -s -H "X-API-Key: $KEY" "$BASE/runs?limit=10" \\
  | jq '.data | {n: (.items|length), next: .next_cursor}'`}</CodeBlock>

            <CodeBlock lang="javascript">{`const BASE = "https://your-app.example.com/api/v1";
const headers = { "X-API-Key": process.env.CAROUSEL_API_KEY,
                  "Content-Type": "application/json" };

// Submit async job — result lives in .data
const { data: job } = await fetch(\`\${BASE}/jobs\`, {
  method: "POST",
  headers,
  body: JSON.stringify({ kind: "render", topic: "f1", design: "newsflash" }),
}).then(r => r.json());

// Poll — unwrap envelope each time
let cur;
do {
  await new Promise(r => setTimeout(r, 3000));
  const env = await fetch(\`\${BASE}/jobs/\${job.job_id}\`, { headers }).then(r => r.json());
  cur = env.data;
} while (cur.status === "queued" || cur.status === "running");

if (cur.status === "failed") throw new Error(cur.error.message);
console.log(cur.result.caption, cur.result.slides.map((s: { url: string }) => s.url));`}</CodeBlock>

            <CodeBlock lang="python">{`import os, time, requests

BASE = "https://your-app.example.com/api/v1"
HEADERS = {"X-API-Key": os.environ["CAROUSEL_API_KEY"]}

# Submit — unwrap .data
job = requests.post(f"{BASE}/jobs", headers=HEADERS,
                    json={"kind": "render", "topic": "f1",
                          "design": "newsflash"}).json()["data"]

while True:
    cur = requests.get(f"{BASE}/jobs/{job['job_id']}",
                       headers=HEADERS).json()["data"]
    if cur["status"] in ("succeeded", "failed"):
        break
    time.sleep(3)

if cur["status"] == "failed":
    raise RuntimeError(cur["error"]["message"])

run = cur["result"]
print(run["caption"])
for slide in run["slides"]:
    print(slide["url"])

# Download ZIP (binary — not enveloped)
zip_bytes = requests.get(
    f"{BASE}/runs/{run['run_id']}/export", headers=HEADERS).content
open(f"{run['run_id']}.zip", "wb").write(zip_bytes)`}</CodeBlock>
          </Section>

          {/* ── Endpoints ────────────────────────────────────────────────── */}
          <Section id="endpoints" title="Endpoints">
            {ENDPOINTS.map((ep) => (
              <EndpointCard key={`${ep.method}:${ep.path}`} ep={ep} />
            ))}
          </Section>

          {/* ── Errors ───────────────────────────────────────────────────── */}
          <Section id="errors" title="Errors">
            <p>
              Exactly <strong>7 codes</strong> shared across all services using this
              standard. Errors always follow the{" "}
              <a href="#response-envelope" className="text-accent hover:underline">
                response envelope
              </a>{" "}
              with <code>success: false</code> and an{" "}
              <code className="text-accent">error.code</code> string.
            </p>
            <CodeBlock lang="json">{`{
  "success": false,
  "error": {
    "code": "rate_limited",
    "message": "rate limit exceeded: 30 per 1 minute"
  },
  "meta": { "request_id": "ab12cd34" }
}`}</CodeBlock>
            <table className="w-full text-xs border-collapse">
              <thead>
                <tr className="text-left border-b border-ink-700/60">
                  <th className="py-2 pr-4 font-semibold text-ink-100">HTTP</th>
                  <th className="py-2 pr-4 font-semibold text-ink-100">code</th>
                  <th className="py-2 font-semibold text-ink-100">When</th>
                </tr>
              </thead>
              <tbody>
                {ERROR_CODES.map((e) => (
                  <tr key={e.code} className="border-b border-ink-700/30 align-top">
                    <td className="py-2 pr-4 font-mono text-ink-100">{e.code}</td>
                    <td className="py-2 pr-4 font-mono text-accent text-[11px]">{e.key}</td>
                    <td className="py-2 text-ink-300">{e.meaning}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Section>

          {/* ── Rate limits ──────────────────────────────────────────────── */}
          <Section id="rate-limits" title="Rate limits">
            <p>
              Limits are <strong>per API key</strong>, in-memory, sliding window. Two tiers:
            </p>
            <ul className="list-disc list-inside text-ink-300 space-y-1">
              <li>
                <strong className="text-ink-100">Heavy</strong> — 30 req/min by default.
                Applies to <code>/actions/render*</code>, <code>POST /jobs</code>,{" "}
                <code>/runs/{`{id}`}/export</code>. Configure via{" "}
                <code>CAROUSEL_API_RATE_LIMIT</code>.
              </li>
              <li>
                <strong className="text-ink-100">Light</strong> — 120 req/min by default.
                Applies to discovery, preview, run/job reads. Configure via{" "}
                <code>CAROUSEL_API_RATE_LIMIT_LIGHT</code>.
              </li>
            </ul>
            <p>
              Exceeded responses come back as <code>429</code> with a{" "}
              <code>Retry-After</code> header (seconds). Async throughput is also bounded
              by <code>CAROUSEL_API_JOB_WORKERS</code> (default 2 concurrent renders) —
              enqueue is instant, but only N run at once.
            </p>
          </Section>

          {/* ── Async jobs ───────────────────────────────────────────────── */}
          <Section id="async-jobs" title="Async jobs">
            <p>
              A render takes <strong>10–40s</strong> (image fetching dominates). Rather
              than hold an HTTP connection open that long — fragile behind a reverse proxy
              / Tailscale Funnel — submit a job to{" "}
              <code className="text-accent">POST /api/v1/jobs</code> and poll, or supply a{" "}
              <code>webhook_url</code>.
            </p>
            <CodeBlock lang="text">{`queued ──▶ running ──▶ succeeded   (data.result: RenderOut)
                   └──▶ failed      (data.error: { code, message, details? })`}</CodeBlock>
            <p>
              Poll <code>status_url</code> every 2–5s. A failed render (e.g. no fresh
              stories today) ends in <code>failed</code> with the pipeline diagnostics
              under <code>error.details</code> — the worker never hangs.
            </p>
            <div className="border border-amber-500/30 bg-amber-500/5 rounded-xl p-4">
              <p className="text-amber-300 font-medium text-xs mb-1">
                Durability — read this
              </p>
              <p className="text-xs text-ink-300">
                The job store is <strong>in-process and single-instance</strong>: a{" "}
                <code>job_id</code> is ephemeral. It is evicted ~1h after completion
                (<code>CAROUSEL_API_JOB_TTL</code>) and dropped on a restart/redeploy. The
                durable handle is <code>run_id</code> — once a render succeeds, its slides
                + caption persist on disk and stay readable via{" "}
                <code className="text-accent">GET /api/v1/runs/{`{run_id}`}</code> even
                after the job is gone. Persist the <code>run_id</code> and treat a{" "}
                <code>404</code> on a <code>job_id</code> as "poll the run instead."
              </p>
            </div>
          </Section>

          {/* ── Webhooks ─────────────────────────────────────────────────── */}
          <Section id="webhooks" title="Webhooks">
            <p>
              Pass <code className="text-accent">webhook_url</code> on{" "}
              <code>POST /api/v1/jobs</code> and the server POSTs the completed{" "}
              <strong>envelope</strong> when the job reaches a terminal state — on both
              succeeded and failed:
            </p>
            <CodeBlock lang="json">{`{
  "success": true,
  "data": {
    "job_id": "9f1c2a...",
    "kind": "render",
    "status": "succeeded",
    "finished_at": 1715000034,
    "result": { "...RenderOut..." },
    "error": null
  },
  "meta": { "request_id": "ab12cd34" }
}`}</CodeBlock>
            <p>
              When the operator sets <code>CAROUSEL_WEBHOOK_SECRET</code>, each delivery
              carries an{" "}
              <code>X-Carousel-Signature: sha256=&lt;hex&gt;</code> header — an HMAC-SHA256
              of the raw body. Verify it before trusting the payload:
            </p>
            <CodeBlock lang="python">{`import hashlib, hmac

def verify(raw_body: bytes, header: str, secret: str) -> bool:
    expected = "sha256=" + hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header or "")`}</CodeBlock>
            <p className="text-xs text-ink-400">
              Delivery is best-effort: 5s timeout, no redirects, one retry. Your receiver
              should be idempotent and return 2xx quickly.{" "}
              <strong>SSRF rules:</strong> <code>webhook_url</code> must be{" "}
              <code>https://</code> and resolve to a public IP — loopback, RFC1918,
              link-local and the CGNAT/Tailscale <code>100.64.0.0/10</code> range are
              rejected before the POST. The operator can allow a private receiver via{" "}
              <code>CAROUSEL_WEBHOOK_ALLOW_HOSTS</code>.
            </p>
          </Section>

          {/* ── API key management ───────────────────────────────────────── */}
          <Section id="api-key-management" title="API key management">
            <p className="text-sm text-ink-300 border-l-2 border-accent/60 pl-3">
              <strong className="text-ink-100">
                Integrating against an instance you don&apos;t operate?
              </strong>{" "}
              You don&apos;t mint your own key — request a scoped key from whoever runs
              that instance. They create it with the admin flow below and hand you the{" "}
              <code className="text-accent">csk_…</code> secret (shown once). Everything
              else in this section is for the operator.
            </p>
            <p>
              Admin-only. The raw secret (<code>csk_...</code>) is returned{" "}
              <strong>once</strong> at creation; only its hash is stored. Provision the
              first key by bootstrapping via environment, then use it to mint scoped keys:
            </p>
            <CodeBlock lang="bash">{`# Bootstrap: set an admin key in the environment
export CAROUSEL_API_KEYS="admin:$(openssl rand -hex 24)"

# Create a read+write consumer key
curl -s -H "X-API-Key: $ADMIN" -H "Content-Type: application/json" \\
  -d '{"name":"partner_acme","scopes":["read","write"]}' \\
  "$BASE/api-keys" | jq .data    # -> { key_id, key: "csk_...", scopes, ... }

# List all keys (no raw secrets)
curl -s -H "X-API-Key: $ADMIN" "$BASE/api-keys" | jq .data

# Revoke a key
curl -s -X DELETE -H "X-API-Key: $ADMIN" "$BASE/api-keys/<key_id>" | jq .data`}</CodeBlock>
            <p className="text-xs text-ink-400">
              Rotate a key: add a new key, hand it over, then revoke the old one. Keys are
              never logged — only the key <em>name</em> appears in access logs.
            </p>
          </Section>

          {/* ── Browsers & key safety ────────────────────────────────────── */}
          <Section id="browser-key-safety" title="Browsers &amp; key safety">
            <p>
              Building a <strong>browser frontend</strong> on top of this API?{" "}
              <strong className="text-ink-100">
                Never put the API key in browser JavaScript
              </strong>{" "}
              — anyone can read it. Use a Backend-for-Frontend (BFF): your own server
              holds the key and proxies calls; the browser talks only to your server.
            </p>
            <CodeBlock lang="text">{`Browser ──(no key)──▶ Your backend ──(X-API-Key)──▶ Carousel /api/v1`}</CodeBlock>
            <p className="text-xs text-ink-400">
              <code>CAROUSEL_API_CORS</code> defaults to <code>*</code> (the typical
              caller is server-to-server). Listing browser origins there is only for a
              trusted same-origin admin tool — it is not a green light for key-in-browser.
              See{" "}
              <a
                href={`${examplesHref}/bff_proxy.mjs`}
                target="_blank"
                rel="noopener noreferrer"
                className="text-accent hover:underline"
              >
                bff_proxy.mjs
              </a>{" "}
              +{" "}
              <a
                href={`${examplesHref}/browser.ts`}
                target="_blank"
                rel="noopener noreferrer"
                className="text-accent hover:underline"
              >
                browser.ts
              </a>{" "}
              for a working pair.
            </p>
          </Section>
        </main>

        <aside className="hidden lg:block">
          <nav className="sticky top-24 text-xs space-y-1 text-ink-300">
            <div className="text-[10px] uppercase tracking-[0.14em] text-ink-400 mb-2">
              On this page
            </div>
            {[
              ["response-envelope", "Response envelope"],
              ["authentication", "Auth & scopes"],
              ["pagination", "Pagination"],
              ["quickstart", "Quickstart"],
              ["endpoints", "Endpoints"],
              ["errors", "Errors"],
              ["rate-limits", "Rate limits"],
              ["async-jobs", "Async jobs"],
              ["webhooks", "Webhooks"],
              ["api-key-management", "API key mgmt"],
              ["browser-key-safety", "Browsers & keys"],
            ].map(([id, label]) => (
              <a
                key={id}
                href={`#${id}`}
                className="block py-1 hover:text-accent transition"
              >
                {label}
              </a>
            ))}
          </nav>
        </aside>
      </div>
    </div>
  );
}

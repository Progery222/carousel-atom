import { Link } from "react-router-dom";
import { API_BASE } from "../api";

/** Endpoint reference data — single source of truth for the docs page. */
interface EndpointDoc {
  method: "GET" | "POST";
  path: string;
  summary: string;
  description: string;
  status?: string; // success status code shown on the card (e.g. "202")
  query?: { name: string; type: string; required: boolean; desc: string }[];
  body?: string; // JSON example
  response: string; // JSON example
  rateLimit: "heavy" | "light" | "none";
}

const ENDPOINTS: EndpointDoc[] = [
  {
    method: "GET",
    path: "/api/v1/topics",
    summary: "List available topics",
    description:
      "Every topic configured in backend/topics/. Use the slug field for /render calls.",
    response: `[
  {
    "slug": "f1",
    "name": "F1 Daily",
    "source_count": 8,
    "news_per_carousel": 5
  }
]`,
    rateLimit: "light",
  },
  {
    method: "GET",
    path: "/api/v1/designs",
    summary: "List available designs",
    description:
      "Every design template registered in backend/designs/__init__.py. Use the slug field for /render calls.",
    response: `[
  {
    "slug": "newsflash",
    "name": "Newsflash",
    "description": "Hero photo + bold headline on a brand-colored card."
  }
]`,
    rateLimit: "light",
  },
  {
    method: "GET",
    path: "/api/v1/preview/articles",
    summary: "Preview fresh article candidates (no render)",
    description:
      "Runs the news fetch + freshness + scoring pipeline without rendering slides. Use this to pre-flight a carousel — show the user candidate stories and let them pick.",
    query: [
      { name: "topic", type: "string", required: true, desc: "Topic slug" },
      { name: "limit", type: "int", required: false, desc: "Max candidates (default 12)" },
    ],
    response: `{
  "topic": "f1",
  "raw": 87,
  "fresh": 42,
  "enriched": 18,
  "candidates": [
    {
      "title": "Verstappen wins Monaco GP",
      "url": "https://...",
      "source": "f1.com",
      "image_url": "https://...",
      "description": "...",
      "score": 4.7
    }
  ]
}`,
    rateLimit: "light",
  },
  {
    method: "POST",
    path: "/api/v1/render",
    summary: "Render a fresh carousel (sync)",
    description:
      "Pulls fresh news for the topic, scores + dedupes, renders slides with the chosen design, generates a caption. Returns absolute slide URLs you can download. Synchronous — blocks 10–40s. For anything user-facing or behind a proxy, prefer POST /api/v1/jobs (async). An unknown topic/design returns 404 before any work starts; oversized bodies return 422.",
    body: `{
  "topic": "f1",
  "design": "newsflash",
  "mark_seen": true,
  "cross_topic_dedup": false,
  "deliver": ""
}`,
    response: `{
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
    { "index": 0, "url": "https://api.example.com/output/f1/.../slide_0.png" }
  ],
  "diagnostics": { "raw": 87, "fresh": 42, "after_enrich": 18,
                   "drop_reasons": { "seen": 23 } }
}`,
    rateLimit: "heavy",
  },
  {
    method: "POST",
    path: "/api/v1/render/edit",
    summary: "Re-render with edited articles",
    description:
      "Skip the network fetch — supply your own article list (e.g. user-edited titles, swapped image URLs) and render slides from them. mark_seen is always false on this route.",
    body: `{
  "topic": "f1",
  "design": "newsflash",
  "articles": [
    { "title": "...", "url": "...", "source": "...",
      "image_url": "...", "description": "..." }
  ]
}`,
    response: `(same shape as /render)`,
    rateLimit: "heavy",
  },
  {
    method: "POST",
    path: "/api/v1/render/partial",
    summary: "Per-slot re-roll render",
    description:
      "Mix locked and re-rolled slots. Items that are null get a fresh story from the pipeline; non-null items are kept verbatim.",
    body: `{
  "topic": "f1",
  "design": "newsflash",
  "articles": [
    { "title": "Locked slide 1", "url": "...", "source": "...", "image_url": "..." },
    null,
    null
  ]
}`,
    response: `(same shape as /render)`,
    rateLimit: "heavy",
  },
  {
    method: "POST",
    path: "/api/v1/jobs",
    summary: "Submit an async render job",
    status: "202",
    description:
      "Enqueue a render and return immediately with a job_id. Poll GET /api/v1/jobs/{job_id} or pass a webhook_url to be notified on completion. The body mirrors the sync render endpoints, tagged with kind: render | render_edit | render_partial. webhook_url is optional (https-only, SSRF-guarded).",
    body: `{
  "kind": "render",
  "topic": "f1",
  "design": "newsflash",
  "webhook_url": "https://my-service.example.com/carousel/done"
}`,
    response: `// 202 Accepted
{
  "job_id": "9f1c2a...",
  "kind": "render",
  "status": "queued",
  "created_at": 1715000000,
  "status_url": "https://api.example.com/api/v1/jobs/9f1c2a..."
}`,
    rateLimit: "heavy",
  },
  {
    method: "GET",
    path: "/api/v1/jobs/{job_id}",
    summary: "Get async job status & result",
    description:
      "Poll for the job state: queued → running → succeeded | failed. On success, result holds the full RenderOut; on failure, error holds { code, message, details }. A job_id is ephemeral (in-memory, single-instance) — it 404s after a ~1h TTL or a restart. The durable handle is result.run_id (see GET /runs/{run_id}).",
    response: `{
  "job_id": "9f1c2a...",
  "kind": "render",
  "status": "succeeded",
  "created_at": 1715000000,
  "started_at": 1715000001,
  "finished_at": 1715000034,
  "result": { "status": "ok", "run_id": "f1_newsflash_...",
              "caption": "...", "slides": [ ... ], "articles": [ ... ] },
  "error": null
}`,
    rateLimit: "light",
  },
  {
    method: "GET",
    path: "/api/v1/runs/{run_id}",
    summary: "Re-fetch a finished run",
    description:
      "Reconstruct a previously rendered run from disk: caption, articles and absolute slide URLs. Durable counterpart to a job — keeps working across restarts and after the job is evicted. Degrades to slides-only for very old runs that predate run.json. Pass ?topic=... if a slug with underscores can't be recovered from run_id.",
    query: [
      { name: "topic", type: "string", required: false, desc: "Topic slug (only if run_id parsing is ambiguous)" },
    ],
    response: `(same shape as /render — a RenderOut)`,
    rateLimit: "light",
  },
  {
    method: "GET",
    path: "/api/v1/export/{run_id}.zip",
    summary: "Download a rendered run as a ZIP",
    description:
      "Returns a ZIP containing slide_*.png, caption.txt, and metadata.json. The topic slug is auto-detected from run_id; pass ?topic=... explicitly if the slug contains underscores.",
    query: [
      { name: "topic", type: "string", required: false, desc: "Topic slug (only if run_id parsing is ambiguous)" },
    ],
    response: `<binary application/zip>
Content-Disposition: attachment; filename="<run_id>.zip"`,
    rateLimit: "heavy",
  },
  {
    method: "GET",
    path: "/api/v1/health",
    summary: "Liveness check (no auth)",
    description: "Always returns ok=true. No X-API-Key required. Use it for uptime monitoring without burning your rate-limit budget.",
    response: `{ "ok": true, "service": "carousel-studio", "version": "1" }`,
    rateLimit: "none",
  },
];

const ERROR_CODES: { code: number; key: string; meaning: string }[] = [
  { code: 400, key: "bad_request", meaning: "Malformed request (e.g. unknown delivery adapter)." },
  { code: 401, key: "unauthorized", meaning: "Missing or invalid X-API-Key." },
  { code: 404, key: "not_found", meaning: "Unknown topic, design, run, or job." },
  { code: 409, key: "conflict / no_articles / no_fresh / no_usable", meaning: "Pipeline couldn't assemble a carousel. See details (diagnostics)." },
  { code: 422, key: "unprocessable_entity", meaning: "Request body failed validation (bad slug, oversized fields, >20 articles). See details (invalid fields)." },
  { code: 429, key: "rate_limited", meaning: "Per-key rate limit exceeded. See Retry-After header." },
  { code: 503, key: "service_unavailable", meaning: "Public API disabled — operator has not set CAROUSEL_API_KEYS." },
];

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
            <div className="text-[11px] text-ink-300">Public /api/v1 reference</div>
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
            Generate TikTok / Instagram-ready news carousels from your own
            service. Key-authed REST API with sync &amp; async (job + webhook)
            rendering. Returns PNG slides + a caption you can post directly.
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

          <Section id="authentication" title="Authentication">
            <p>
              Every request to <code className="text-accent">/api/v1/*</code> (except{" "}
              <code className="text-accent">/api/v1/health</code>) must include an{" "}
              <code className="text-accent">X-API-Key</code> header. Keys are configured
              by the server operator via the <code>CAROUSEL_API_KEYS</code> environment
              variable.
            </p>
            <CodeBlock lang="bash">{`# On the server (one-time setup)
export CAROUSEL_API_KEYS="internal:abc123,partner_acme:xyz789"

# In every client request
curl -H "X-API-Key: abc123" https://your-app.example.com/api/v1/topics`}</CodeBlock>
            <p className="text-xs text-ink-400">
              If <code>CAROUSEL_API_KEYS</code> is empty, every <code>/api/v1</code>{" "}
              call returns 503. The legacy non-prefixed routes used by the studio
              frontend are unaffected by this setting.
            </p>
          </Section>

          <Section id="quickstart" title="Quickstart">
            <p>
              Recommended flow: submit an <strong>async job</strong>, poll until
              it finishes, then read the slides. (A render takes 10–40s, so a
              long-held sync request can hit proxy/Funnel timeouts.) Ready-to-run
              clients live in{" "}
              <code className="text-accent">docs/examples/</code> (Python,
              curl, Node BFF, browser, webhook receiver).
            </p>
            <CodeBlock lang="curl">{`BASE=https://api.example.com; KEY=your-api-key

# 1. Discover what you can render
curl -H "X-API-Key: $KEY" "$BASE/api/v1/topics"

# 2. Submit an async render → returns a job_id
JOB=$(curl -s -H "X-API-Key: $KEY" -H "Content-Type: application/json" \\
  -d '{"kind":"render","topic":"f1","design":"newsflash"}' \\
  "$BASE/api/v1/jobs" | jq -r .job_id)

# 3. Poll until status == succeeded | failed
curl -H "X-API-Key: $KEY" "$BASE/api/v1/jobs/$JOB" | jq

# 4. Re-fetch any time by run_id (durable; survives restarts)
curl -H "X-API-Key: $KEY" "$BASE/api/v1/runs/<run_id>" | jq`}</CodeBlock>

            <CodeBlock lang="javascript">{`const BASE = "https://api.example.com/api/v1";
const headers = { "X-API-Key": process.env.CAROUSEL_API_KEY,
                  "Content-Type": "application/json" };

// submit
const job = await fetch(\`\${BASE}/jobs\`, {
  method: "POST",
  headers,
  body: JSON.stringify({ kind: "render", topic: "f1", design: "newsflash" }),
}).then(r => r.json());

// poll
let cur;
do {
  await new Promise(r => setTimeout(r, 3000));
  cur = await fetch(\`\${BASE}/jobs/\${job.job_id}\`, { headers }).then(r => r.json());
} while (cur.status === "queued" || cur.status === "running");

if (cur.status === "failed") throw new Error(cur.error.message);
console.log(cur.result.caption, cur.result.slides.map(s => s.url));`}</CodeBlock>

            <CodeBlock lang="python">{`import os, time, requests

BASE = "https://api.example.com/api/v1"
HEADERS = {"X-API-Key": os.environ["CAROUSEL_API_KEY"]}

job = requests.post(f"{BASE}/jobs", headers=HEADERS,
                    json={"kind": "render", "topic": "f1", "design": "newsflash"}).json()

while True:
    cur = requests.get(f"{BASE}/jobs/{job['job_id']}", headers=HEADERS).json()
    if cur["status"] in ("succeeded", "failed"):
        break
    time.sleep(3)

if cur["status"] == "failed":
    raise RuntimeError(cur["error"])

run = cur["result"]
print(run["caption"])
for slide in run["slides"]:
    print(slide["url"])

# Download the run as a ZIP
zip_bytes = requests.get(f"{BASE}/export/{run['run_id']}.zip", headers=HEADERS).content
open(f"{run['run_id']}.zip", "wb").write(zip_bytes)`}</CodeBlock>
            <p className="text-xs text-ink-400">
              Prefer the sync path for quick scripts? <code>POST /api/v1/render</code>{" "}
              with the same body minus <code>kind</code> returns the finished
              result directly — use a client timeout ≥ 60s.
            </p>
          </Section>

          <Section id="endpoints" title="Endpoints">
            {ENDPOINTS.map((ep) => (
              <EndpointCard key={ep.path} ep={ep} />
            ))}
          </Section>

          <Section id="errors" title="Errors">
            <p>
              All <code>/api/v1</code> errors follow a unified envelope:
            </p>
            <CodeBlock lang="json">{`{
  "error": {
    "code": "rate_limited",
    "message": "rate limit exceeded: 30 per 1 minute",
    "request_id": "ab12cd34ef56"
  }
}`}</CodeBlock>
            <p>
              For pipeline failures (409), the original diagnostics dictionary is
              preserved under <code>error.details</code> so you can introspect why
              the carousel couldn't be assembled (raw count, fresh count,{" "}
              drop_reasons breakdown).
            </p>
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

          <Section id="rate-limits" title="Rate limits">
            <p>
              Limits are <strong>per API key</strong>, in-memory, sliding window.
              Two tiers:
            </p>
            <ul className="list-disc list-inside text-ink-300 space-y-1">
              <li>
                <strong className="text-ink-100">Heavy</strong> — 30 req/min by
                default. Applies to <code>/render*</code>, <code>/jobs</code>{" "}
                (submit), <code>/export/*.zip</code>. Configure via{" "}
                <code>CAROUSEL_API_RATE_LIMIT</code>.
              </li>
              <li>
                <strong className="text-ink-100">Light</strong> — 120 req/min by
                default. Applies to <code>/topics</code>, <code>/designs</code>,{" "}
                <code>/preview/articles</code>, <code>/jobs/{`{id}`}</code>,{" "}
                <code>/runs/{`{id}`}</code>. Configure via{" "}
                <code>CAROUSEL_API_RATE_LIMIT_LIGHT</code>.
              </li>
            </ul>
            <p>
              Exceeded responses come back as <code>429</code> with a{" "}
              <code>Retry-After</code> header (seconds). Async throughput is also
              bounded by <code>CAROUSEL_API_JOB_WORKERS</code> (default 2
              concurrent renders) — enqueue is instant, but only N run at once.
            </p>
          </Section>

          <Section id="request-tracing" title="Request tracing">
            <p>
              Every response includes an <code>X-Request-ID</code> header. If you
              send your own (also via <code>X-Request-ID</code>), it is echoed back
              and used in server logs and error responses so correlation is one-step.
            </p>
          </Section>

          <Section id="async-jobs" title="Async jobs">
            <p>
              A render takes <strong>10–40s</strong> (image fetching dominates).
              Rather than hold an HTTP connection open that long — fragile behind
              a reverse proxy / Tailscale Funnel — submit a job to{" "}
              <code>POST /api/v1/jobs</code> and poll, or supply a{" "}
              <code>webhook_url</code>.
            </p>
            <CodeBlock lang="text">{`queued ──▶ running ──▶ succeeded   (result: RenderOut)
                   └──▶ failed      (error: { code, message, details? })`}</CodeBlock>
            <p>
              Poll <code>status_url</code> every 2–5s. A failed render (e.g. no
              fresh stories today) ends in <code>failed</code> with the pipeline
              diagnostics under <code>error.details</code> — the worker never
              hangs.
            </p>
            <div className="border border-amber-500/30 bg-amber-500/5 rounded-xl p-4">
              <p className="text-amber-300 font-medium text-xs mb-1">
                Durability — read this
              </p>
              <p className="text-xs text-ink-300">
                The job store is <strong>in-process and single-instance</strong>:
                a <code>job_id</code> is ephemeral. It is evicted ~1h after
                completion (<code>CAROUSEL_API_JOB_TTL</code>) and dropped on a
                restart/redeploy. The durable handle is <code>run_id</code> —
                once a render succeeds, its slides + caption persist on disk and
                stay readable via <code>GET /api/v1/runs/{`{run_id}`}</code> even
                after the job is gone. Persist the <code>run_id</code> and treat a{" "}
                <code>404</code> on a <code>job_id</code> as "poll the run
                instead." Submitting the same render twice is not deduplicated.
              </p>
            </div>
          </Section>

          <Section id="webhooks" title="Webhooks">
            <p>
              Pass <code>webhook_url</code> on <code>POST /api/v1/jobs</code> and
              the server POSTs the result when the job reaches a terminal state —{" "}
              <strong>on both succeeded and failed</strong>:
            </p>
            <CodeBlock lang="json">{`{
  "job_id": "9f1c2a...",
  "kind": "render",
  "status": "succeeded",
  "result": { "...RenderOut, or null on failure..." },
  "error": null,
  "finished_at": 1715000034
}`}</CodeBlock>
            <p>
              When the operator sets <code>CAROUSEL_WEBHOOK_SECRET</code>, each
              delivery carries an <code>X-Carousel-Signature: sha256=&lt;hex&gt;</code>{" "}
              header — an HMAC-SHA256 of the raw body. Verify it before trusting
              the payload:
            </p>
            <CodeBlock lang="python">{`import hashlib, hmac

def verify(raw_body: bytes, header: str, secret: str) -> bool:
    expected = "sha256=" + hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header or "")`}</CodeBlock>
            <p className="text-xs text-ink-400">
              Delivery is best-effort: 5s timeout, no redirects, one retry. Your
              receiver should be idempotent and return 2xx quickly.{" "}
              <strong>SSRF rules:</strong> <code>webhook_url</code> must be{" "}
              <code>https://</code> and resolve to a public IP — loopback,
              RFC1918, link-local and the CGNAT/Tailscale{" "}
              <code>100.64.0.0/10</code> range are rejected before the POST
              (best-effort — re-resolution at connect time means a DNS-rebinding
              caller could bypass it; gate untrusted callers with{" "}
              <code>CAROUSEL_WEBHOOK_ALLOW_HOSTS</code> + network egress controls).
              The operator can allow a private receiver via{" "}
              <code>CAROUSEL_WEBHOOK_ALLOW_HOSTS</code>.
            </p>
          </Section>

          <Section id="browser-key-safety" title="Browsers & key safety">
            <p>
              Building a <strong>browser frontend</strong> on top of this API?{" "}
              <strong className="text-ink-100">
                Never put the API key in browser JavaScript
              </strong>{" "}
              — anyone can read it. Use a Backend-for-Frontend (BFF): your own
              server holds the key and proxies calls; the browser talks only to
              your server.
            </p>
            <CodeBlock lang="text">{`Browser ──(no key)──▶ Your backend ──(X-API-Key)──▶ Carousel /api/v1`}</CodeBlock>
            <p className="text-xs text-ink-400">
              <code>CAROUSEL_API_CORS</code> defaults to <code>*</code> (the
              typical caller is server-to-server). Listing browser origins there
              is only for a trusted same-origin admin tool — it is not a green
              light for key-in-browser. See{" "}
              <code>docs/examples/bff_proxy.mjs</code> +{" "}
              <code>browser.ts</code> for a working pair.
            </p>
          </Section>
        </main>

        <aside className="hidden lg:block">
          <nav className="sticky top-24 text-xs space-y-1 text-ink-300">
            <div className="text-[10px] uppercase tracking-[0.14em] text-ink-400 mb-2">
              On this page
            </div>
            {[
              ["authentication", "Authentication"],
              ["quickstart", "Quickstart"],
              ["endpoints", "Endpoints"],
              ["async-jobs", "Async jobs"],
              ["webhooks", "Webhooks"],
              ["browser-key-safety", "Browsers & keys"],
              ["errors", "Errors"],
              ["rate-limits", "Rate limits"],
              ["request-tracing", "Request tracing"],
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

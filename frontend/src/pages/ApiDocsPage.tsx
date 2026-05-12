import { Link } from "react-router-dom";
import { API_BASE } from "../api";

/** Endpoint reference data — single source of truth for the docs page. */
interface EndpointDoc {
  method: "GET" | "POST";
  path: string;
  summary: string;
  description: string;
  query?: { name: string; type: string; required: boolean; desc: string }[];
  body?: string; // JSON example
  response: string; // JSON example
  rateLimit: "heavy" | "light";
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
    summary: "Render a fresh carousel",
    description:
      "Pulls fresh news for the topic, scores + dedupes, renders slides with the chosen design, generates a caption. Returns absolute slide URLs you can download. Sync — takes 10–30 seconds.",
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
    method: "GET",
    path: "/api/v1/export/{run_id}.zip",
    summary: "Download a rendered run as a ZIP",
    description:
      "Returns a ZIP containing slide_*.png, caption.txt (when present), and metadata.json. The topic slug is auto-detected from run_id; pass ?topic=... explicitly if the slug contains underscores.",
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
    description: "Always returns ok=true. Use it for uptime monitoring without burning your rate-limit budget.",
    response: `{ "ok": true, "service": "carousel-studio", "version": "1" }`,
    rateLimit: "light",
  },
];

const ERROR_CODES: { code: number; key: string; meaning: string }[] = [
  { code: 400, key: "bad_request", meaning: "Validation failed (e.g. empty articles list, unknown delivery adapter)." },
  { code: 401, key: "unauthorized", meaning: "Missing or invalid X-API-Key." },
  { code: 404, key: "not_found", meaning: "Topic or run not found." },
  { code: 409, key: "conflict / no_articles / no_fresh / no_usable", meaning: "Pipeline couldn't assemble a carousel. See details.diagnostics." },
  { code: 413, key: "payload_too_large", meaning: "Uploaded image exceeds 12 MB." },
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
        <span className="text-[10px] uppercase tracking-wider text-ink-400 ml-auto">
          {ep.rateLimit === "heavy" ? "Heavy tier" : "Light tier"}
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
            Generate TikTok / Instagram-ready news carousels from your own service.
            Authenticated server-to-server REST API. Returns PNG slides + a caption
            you can post directly.
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
              <code className="text-accent">/health</code>) must include an{" "}
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
            <p>Three minimal end-to-end recipes:</p>
            <CodeBlock lang="curl">{`# 1. List topics
curl -H "X-API-Key: $KEY" https://api.example.com/api/v1/topics

# 2. Render a carousel
curl -X POST https://api.example.com/api/v1/render \\
  -H "X-API-Key: $KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"topic":"f1","design":"newsflash"}'

# 3. Download the result as a ZIP
curl -H "X-API-Key: $KEY" \\
  -o slides.zip \\
  https://api.example.com/api/v1/export/<run_id>.zip`}</CodeBlock>

            <CodeBlock lang="javascript">{`const BASE = "https://api.example.com/api/v1";
const headers = { "X-API-Key": process.env.CAROUSEL_API_KEY };

const topics = await fetch(\`\${BASE}/topics\`, { headers }).then(r => r.json());

const render = await fetch(\`\${BASE}/render\`, {
  method: "POST",
  headers: { ...headers, "Content-Type": "application/json" },
  body: JSON.stringify({ topic: "f1", design: "newsflash" }),
}).then(r => r.json());

console.log(render.slides.map(s => s.url));
console.log(render.caption);`}</CodeBlock>

            <CodeBlock lang="python">{`import os, requests

BASE = "https://api.example.com/api/v1"
HEADERS = {"X-API-Key": os.environ["CAROUSEL_API_KEY"]}

topics = requests.get(f"{BASE}/topics", headers=HEADERS).json()

r = requests.post(
    f"{BASE}/render",
    headers=HEADERS,
    json={"topic": "f1", "design": "newsflash"},
).json()

for slide in r["slides"]:
    print(slide["url"])

# Download as zip
zip_bytes = requests.get(
    f"{BASE}/export/{r['run_id']}.zip", headers=HEADERS
).content
open(f"{r['run_id']}.zip", "wb").write(zip_bytes)`}</CodeBlock>
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
                default. Applies to <code>/render</code>, <code>/render/edit</code>,{" "}
                <code>/render/partial</code>, <code>/export/*.zip</code>. Configure
                via <code>CAROUSEL_API_RATE_LIMIT</code>.
              </li>
              <li>
                <strong className="text-ink-100">Light</strong> — 120 req/min by
                default. Applies to <code>/topics</code>, <code>/designs</code>,{" "}
                <code>/preview/articles</code>. Configure via{" "}
                <code>CAROUSEL_API_RATE_LIMIT_LIGHT</code>.
              </li>
            </ul>
            <p>
              Exceeded responses come back as <code>429</code> with a{" "}
              <code>Retry-After</code> header (seconds).
            </p>
          </Section>

          <Section id="request-tracing" title="Request tracing">
            <p>
              Every response includes an <code>X-Request-ID</code> header. If you
              send your own (also via <code>X-Request-ID</code>), it is echoed back
              and used in server logs and error responses so correlation is one-step.
            </p>
          </Section>

          <Section id="render-timing" title="Async note">
            <p>
              <code>/render</code> is <strong>synchronous</strong> — it returns when
              slides are written to disk (typically 10–30s, dominated by image
              fetching). Use a generous client timeout (≥60s) and avoid putting
              this call directly on a user-facing request thread.
            </p>
            <p>
              If you need fire-and-forget rendering, run the call in your own
              background worker and poll <code>/export/{`{run_id}`}.zip</code>{" "}
              when it returns.
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
              ["errors", "Errors"],
              ["rate-limits", "Rate limits"],
              ["request-tracing", "Request tracing"],
              ["render-timing", "Async note"],
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

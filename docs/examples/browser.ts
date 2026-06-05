// Browser-side client — talks to YOUR BFF proxy (bff_proxy.mjs), never to
// Carousel directly, so the API key stays server-side. No key in this file.
//
// `BFF` is your own backend origin (same-origin in prod -> set to "").

const BFF = ""; // e.g. "https://my-app.example.com"

// ── Response envelope ────────────────────────────────────────────────────────
// Every JSON response from /api/v1 is wrapped in this envelope.
// Success: { success: true,  data: T,    meta: { request_id } }
// Error:   { success: false, error: ..., meta: { request_id } }
type Envelope<T> = {
  success: boolean;
  data: T;
  error?: { code: string; message: string; details?: unknown };
  meta: { request_id: string };
};

// ── Domain types ─────────────────────────────────────────────────────────────
type Slide = { index: number; url: string };
type RenderOut = {
  status: string;
  run_id: string;
  caption: string;
  slides: Slide[];
  articles: { title: string; url: string; source: string }[];
};
type JobOut = {
  job_id: string;
  status: "queued" | "running" | "succeeded" | "failed";
  result: RenderOut | null;
  error: { code: string; message: string } | null;
};

// ── Low-level fetch ──────────────────────────────────────────────────────────
async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${BFF}${path}`, {
    ...init,
    headers: { "content-type": "application/json", ...(init?.headers || {}) },
  });
  if (!r.ok) throw new Error(`${r.status}: ${await r.text()}`);
  const env = (await r.json()) as Envelope<T>;
  return env.data;
}

// ── Discovery ────────────────────────────────────────────────────────────────
export async function listTopics() {
  return api<{ slug: string; name: string }[]>("/api/v1/topics");
}

// ── Async render + poll ──────────────────────────────────────────────────────
/** Submit an async render and poll until it finishes. */
export async function renderCarousel(topic: string, design: string): Promise<RenderOut> {
  const job = await api<JobOut>("/api/v1/jobs", {
    method: "POST",
    body: JSON.stringify({ kind: "render", topic, design }),
  });

  // Poll every 3s, bounded by a deadline so a stuck job can't loop forever.
  // The durable handle is result.run_id — persist it if you want to re-fetch
  // later via GET /api/v1/runs/{run_id}.
  const deadline = Date.now() + 180_000;
  while (Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, 3000));
    const cur = await api<JobOut>(`/api/v1/jobs/${job.job_id}`);
    if (cur.status === "succeeded") return cur.result!;
    if (cur.status === "failed") throw new Error(cur.error?.message || "render failed");
  }
  throw new Error("render timed out");
}

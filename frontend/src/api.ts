import type {
  Article,
  Design,
  PreviewResult,
  RenderDiagnostics,
  RenderResult,
  RunHistoryEntry,
  Topic,
} from "./types";

export class RenderError extends Error {
  status: string;
  diagnostics?: RenderDiagnostics;
  constructor(status: string, message: string, diagnostics?: RenderDiagnostics) {
    super(message);
    this.name = "RenderError";
    this.status = status;
    this.diagnostics = diagnostics;
  }
}

interface RenderErrorDetail {
  status?: string;
  diagnostics?: RenderDiagnostics;
}

// In production the frontend is served by the same FastAPI instance that
// hosts the API, so relative URLs ("") just work. For local dev where
// Vite is on :5173 and uvicorn on :8000, set VITE_CAROUSEL_API.
export const API_BASE =
  (import.meta.env?.VITE_CAROUSEL_API as string | undefined) ??
  (import.meta.env?.DEV ? "http://localhost:8000" : "");

/** Slide URLs returned by the backend are root-relative — make them absolute. */
export function absSlideUrl(url: string): string {
  return url.startsWith("http") ? url : `${API_BASE}${url}`;
}

async function jsonOrThrow<T>(r: Response, label: string): Promise<T> {
  if (!r.ok) {
    let detail: unknown = {};
    try {
      detail = await r.json();
    } catch {
      /* swallow */
    }
    throw new Error(`${label} ${r.status}: ${JSON.stringify(detail)}`);
  }
  return r.json();
}

/** Like jsonOrThrow but for /render endpoints: surface the pipeline's
 *  diagnostics breakdown as a typed RenderError so the UI can show
 *  "23 seen, 41 no-image, …" instead of raw JSON. */
async function renderOrThrow(r: Response, label: string): Promise<RenderResult> {
  if (r.ok) return r.json();
  let body: { detail?: RenderErrorDetail } = {};
  try {
    body = await r.json();
  } catch {
    /* swallow */
  }
  const detail = body.detail ?? {};
  const status = detail.status ?? `http_${r.status}`;
  const diag = detail.diagnostics;
  const msg = diag
    ? `${label}: ${status} (raw=${diag.raw}, fresh=${diag.fresh}, kept=${diag.after_enrich})`
    : `${label} ${r.status}: ${JSON.stringify(body)}`;
  throw new RenderError(status, msg, diag);
}

export async function fetchTopics(): Promise<Topic[]> {
  return jsonOrThrow(await fetch(`${API_BASE}/topics`), "/topics");
}

export async function fetchDesigns(): Promise<Design[]> {
  return jsonOrThrow(await fetch(`${API_BASE}/designs`), "/designs");
}

export async function renderCarousel(
  topic: string,
  design: string,
  markSeen = false,
  crossTopicDedup = false,
): Promise<RenderResult> {
  const r = await fetch(`${API_BASE}/render`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      topic,
      design,
      mark_seen: markSeen,
      cross_topic_dedup: crossTopicDedup,
    }),
  });
  return renderOrThrow(r, "/render");
}

export async function rerenderEdited(
  topic: string,
  design: string,
  articles: Article[],
): Promise<RenderResult> {
  const r = await fetch(`${API_BASE}/render/edit`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ topic, design, articles }),
  });
  return renderOrThrow(r, "/render/edit");
}

/** Per-slide re-roll: items that are `null` get a fresh story; non-null
 *  items stay locked in place. */
export async function rerenderPartial(
  topic: string,
  design: string,
  articles: Array<Article | null>,
): Promise<RenderResult> {
  const r = await fetch(`${API_BASE}/render/partial`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ topic, design, articles }),
  });
  return renderOrThrow(r, "/render/partial");
}

export async function fetchPostedRuns(): Promise<RunHistoryEntry[]> {
  return jsonOrThrow(await fetch(`${API_BASE}/runs`), "/runs");
}

export async function previewArticles(
  topic: string,
  limit = 12,
): Promise<PreviewResult> {
  const r = await fetch(
    `${API_BASE}/preview/articles?topic=${encodeURIComponent(topic)}&limit=${limit}`,
  );
  return jsonOrThrow(r, "/preview/articles");
}

export async function resetSeen(topic: string): Promise<{ deleted: number }> {
  const r = await fetch(`${API_BASE}/dedup/reset/${topic}`, { method: "POST" });
  return jsonOrThrow(r, "/dedup/reset");
}

export interface DeliverResult {
  ok: boolean;
  message: string;
  msg_ids: number[];
}

export async function deliverRun(
  runId: string,
  topic: string,
  caption: string,
  deliver = "telegram",
): Promise<DeliverResult> {
  const r = await fetch(`${API_BASE}/deliver/${encodeURIComponent(runId)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ topic, caption, deliver }),
  });
  return jsonOrThrow(r, "/deliver");
}

export async function fetchDeliveries(): Promise<
  Array<{ slug: string; name: string; configured: Record<string, boolean> }>
> {
  return jsonOrThrow(await fetch(`${API_BASE}/deliveries`), "/deliveries");
}

export type RewriteStyle = "punchier" | "factual" | "hook" | "translate_ru";

export async function rewriteHeadline(
  title: string,
  style: RewriteStyle,
): Promise<{ title: string }> {
  const r = await fetch(`${API_BASE}/llm/rewrite-headline`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title, style }),
  });
  return jsonOrThrow(r, "/llm/rewrite-headline");
}

export async function uploadImage(file: File): Promise<{ url: string }> {
  const fd = new FormData();
  fd.append("file", file);
  const r = await fetch(`${API_BASE}/upload-image`, {
    method: "POST",
    body: fd,
  });
  return jsonOrThrow(r, "/upload-image");
}

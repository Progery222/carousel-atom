export interface Topic {
  slug: string;
  name: string;
  source_count: number;
  news_per_carousel: number;
  featured?: boolean;
}

export interface Design {
  slug: string;
  name: string;
  description: string;
}

export interface Slide {
  index: number;
  url: string;
}

export interface Article {
  title: string;
  url: string;
  source: string;
  image_url?: string;
  description?: string;
}

export interface RenderDiagnostics {
  raw: number;
  fresh: number;
  after_enrich: number;
  drop_reasons: Record<string, number>;
}

export interface RenderResult {
  status: string;
  run_id: string;
  topic: string;
  design: string;
  caption: string;
  articles: Article[];
  slides: Slide[];
  diagnostics?: RenderDiagnostics;
}

export interface RunHistoryEntry {
  topic: string;
  run_id: string;
  posted_at: number;
  platform: string;
  slide_count: number | null;
  caption: string | null;
}

/** Local-only history entry stored in localStorage by the studio. */
export interface LocalRun {
  run_id: string;
  topic: string;
  topic_name: string;
  design: string;
  design_name: string;
  created_at: number;
  caption: string;
  slides: Slide[];
  articles: Article[];
}

export interface PreviewCandidate extends Article {
  score: number;
}

export interface PreviewResult {
  topic: string;
  raw: number;
  fresh: number;
  enriched: number;
  candidates: PreviewCandidate[];
}

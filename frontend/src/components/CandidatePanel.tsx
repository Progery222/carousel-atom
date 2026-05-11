import { useEffect, useState } from "react";
import { previewArticles } from "../api";
import type { Article, PreviewCandidate } from "../types";

interface Props {
  topic: string | null;
  /** how many slots the carousel will fill */
  needed: number;
  open: boolean;
  onClose: () => void;
  onConfirm: (selected: Article[]) => Promise<void> | void;
}

export function CandidatePanel({ topic, needed, open, onClose, onConfirm }: Props) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<PreviewCandidate[]>([]);
  const [stats, setStats] = useState<{ raw: number; fresh: number; enriched: number } | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());

  useEffect(() => {
    if (!open || !topic) return;
    setLoading(true);
    setError(null);
    setData([]);
    setPicked(new Set());
    previewArticles(topic, 16)
      .then((res) => {
        setData(res.candidates);
        setStats({ raw: res.raw, fresh: res.fresh, enriched: res.enriched });
        // Pre-select the top `needed` candidates so the user can confirm in one click.
        setPicked(new Set(res.candidates.slice(0, needed).map((c) => c.url)));
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, [open, topic, needed]);

  if (!open) return null;

  const toggle = (url: string) =>
    setPicked((cur) => {
      const next = new Set(cur);
      if (next.has(url)) next.delete(url);
      else next.add(url);
      return next;
    });

  const confirm = async () => {
    const selected = data.filter((c) => picked.has(c.url));
    if (selected.length === 0) return;
    await onConfirm(selected);
  };

  return (
    <div className="fixed inset-0 z-40 bg-ink-900/60 backdrop-blur-sm flex items-center justify-center p-6">
      <div className="bg-ink-800 ring-1 ring-ink-600/50 rounded-2xl shadow-float flex flex-col max-w-3xl w-full max-h-[85vh]">
        <div className="flex items-center justify-between px-6 py-4 border-b border-ink-700/60">
          <div>
            <h2 className="text-sm font-semibold text-ink-100">
              Candidate articles
            </h2>
            <div className="text-[11px] text-ink-300">
              {stats
                ? `${stats.raw} raw · ${stats.fresh} fresh · ${stats.enriched} after quality gate`
                : "Loading…"}
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-ink-300 hover:text-ink-100 text-lg"
            aria-label="close"
          >
            ×
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-3 space-y-2">
          {loading && (
            <div className="text-sm text-ink-300 px-2 py-4">
              Pulling candidates from the upstream feeds…
            </div>
          )}
          {error && (
            <div className="text-xs text-accent-red bg-accent-red/10 border border-accent-red/30 rounded px-3 py-2">
              {error}
            </div>
          )}
          {!loading && data.length === 0 && !error && (
            <div className="text-sm text-ink-300 px-2 py-6">
              No candidates — your seen-store may need a reset.
            </div>
          )}
          {data.map((c) => {
            const sel = picked.has(c.url);
            return (
              <label
                key={c.url}
                className={`flex gap-3 items-start p-3 rounded-xl cursor-pointer transition ${
                  sel
                    ? "bg-accent/10 ring-1 ring-accent/40 text-ink-100"
                    : "bg-ink-700/40 hover:bg-ink-700/70 hover:shadow-soft"
                }`}
              >
                <input
                  type="checkbox"
                  checked={sel}
                  onChange={() => toggle(c.url)}
                  className="mt-1 accent-blue-600"
                />
                {c.image_url ? (
                  <img
                    src={c.image_url}
                    alt=""
                    referrerPolicy="no-referrer"
                    className="w-16 h-16 object-cover rounded border border-ink-700"
                  />
                ) : (
                  <div className="w-16 h-16 rounded bg-ink-700" />
                )}
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium leading-snug">
                    {c.title}
                  </div>
                  <div className="text-[10px] uppercase tracking-wider text-ink-300 mt-1 flex gap-2">
                    <span>{c.source}</span>
                    <span>·</span>
                    <span>score {c.score.toFixed(1)}</span>
                  </div>
                  {c.description && (
                    <div className="text-xs text-ink-300 mt-1 line-clamp-2">
                      {c.description.slice(0, 200)}
                    </div>
                  )}
                </div>
              </label>
            );
          })}
        </div>

        <div className="flex items-center justify-between px-6 py-4 border-t border-ink-700/60 bg-ink-700/20">
          <div className="text-xs text-ink-300">
            <span className="font-semibold text-ink-100">{picked.size}</span> selected · need {needed}
          </div>
          <div className="flex gap-2">
            <button
              onClick={onClose}
              className="px-3.5 py-2 text-xs font-medium bg-ink-700 text-ink-200 rounded-lg hover:bg-ink-600 hover:text-ink-100 transition"
            >
              Cancel
            </button>
            <button
              onClick={confirm}
              disabled={picked.size === 0}
              className="px-4 py-2 text-xs bg-accent text-white rounded-lg font-semibold shadow-soft hover:shadow-card hover:-translate-y-px transition disabled:opacity-60 disabled:translate-y-0 disabled:hover:shadow-soft"
            >
              Render with {picked.size}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

import { useMemo, useState } from "react";
import { absSlideUrl } from "../api";
import type { LocalRun } from "../types";

interface Props {
  runs: LocalRun[];
  activeRunId: string | null;
  onSelect: (run: LocalRun) => void;
  onClear: () => void;
}

/** Sidebar list of recent local runs (stored in localStorage). */
export function HistoryPanel({ runs, activeRunId, onSelect, onClear }: Props) {
  const [query, setQuery] = useState("");

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return runs;
    return runs.filter((r) => {
      const hay = [
        r.topic_name,
        r.design_name,
        r.caption,
        ...r.articles.map((a) => a.title),
      ]
        .join(" ")
        .toLowerCase();
      return hay.includes(q);
    });
  }, [runs, query]);

  if (runs.length === 0) {
    return (
      <div className="text-xs text-ink-300 px-3 py-3 bg-ink-700/40 rounded-xl">
        Generated carousels show up here automatically.
      </div>
    );
  }
  return (
    <div className="space-y-1.5">
      <input
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Filter history…"
        className="w-full px-3 py-2 mb-1 text-xs bg-ink-700/60 rounded-lg text-ink-100 placeholder:text-ink-400 focus:bg-ink-700 focus:outline-none focus:ring-2 focus:ring-accent/40 transition"
      />
      <div className="flex items-center justify-between px-1 pb-1">
        <span className="text-[11px] text-ink-300">
          {query ? `${filtered.length} of ${runs.length}` : `${runs.length} runs`}
        </span>
        <button
          onClick={onClear}
          className="text-[10px] uppercase tracking-wider text-ink-400 hover:text-accent-red transition"
        >
          clear
        </button>
      </div>
      {filtered.length === 0 && (
        <div className="text-xs text-ink-400 px-1 py-2">No matches.</div>
      )}
      {filtered.map((r) => {
        const active = r.run_id === activeRunId;
        const ago = formatAgo(r.created_at);
        const thumb = r.slides[0]?.url;
        return (
          <button
            key={r.run_id}
            onClick={() => onSelect(r)}
            className={`w-full text-left p-2 rounded-xl transition flex items-center gap-2.5 ${
              active
                ? "bg-accent/10 ring-1 ring-accent/40 shadow-soft"
                : "hover:bg-ink-700/70 hover:shadow-soft"
            }`}
          >
            {thumb ? (
              <img
                src={absSlideUrl(thumb)}
                alt=""
                className="w-10 h-12 object-cover rounded-lg flex-shrink-0 shadow-soft"
              />
            ) : (
              <div className="w-10 h-12 bg-ink-700 rounded-lg flex-shrink-0" />
            )}
            <div className="flex-1 min-w-0">
              <div className={`text-xs font-semibold truncate ${active ? "text-accent" : "text-ink-100"}`}>
                {r.topic_name}
              </div>
              <div className="text-[10px] text-ink-300 truncate">
                {r.design_name} · {ago}
              </div>
            </div>
          </button>
        );
      })}
    </div>
  );
}

function formatAgo(ts: number): string {
  const sec = Math.max(1, Math.round((Date.now() - ts) / 1000));
  if (sec < 60) return `${sec}s ago`;
  const min = Math.round(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr}h ago`;
  return `${Math.round(hr / 24)}d ago`;
}

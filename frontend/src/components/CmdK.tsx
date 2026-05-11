import { useEffect, useMemo, useRef, useState } from "react";
import type { Design, LocalRun, Topic } from "../types";

interface Props {
  open: boolean;
  onClose: () => void;
  topics: Topic[];
  designs: Design[];
  runs: LocalRun[];
  onPickTopic: (slug: string) => void;
  onPickDesign: (slug: string) => void;
  onPickRun: (run: LocalRun) => void;
}

type Item =
  | { kind: "topic"; topic: Topic }
  | { kind: "design"; design: Design }
  | { kind: "run"; run: LocalRun };

const ICON: Record<string, string> = {
  topic: "🏷",
  design: "🎨",
  run: "🕘",
};

/** Subsequence-fuzzy match: every char in `q` appears in `s` in order.
 *  Score = lower-is-better (smaller gaps + earlier first match). */
function fuzzyScore(q: string, s: string): number | null {
  if (!q) return 0;
  const Q = q.toLowerCase();
  const S = s.toLowerCase();
  let qi = 0;
  let firstMatch = -1;
  let lastMatch = -1;
  let score = 0;
  for (let si = 0; si < S.length && qi < Q.length; si++) {
    if (S[si] === Q[qi]) {
      if (firstMatch < 0) firstMatch = si;
      if (lastMatch >= 0) score += si - lastMatch - 1;
      lastMatch = si;
      qi++;
    }
  }
  if (qi < Q.length) return null;
  return firstMatch * 2 + score;
}

export function CmdK({
  open,
  onClose,
  topics,
  designs,
  runs,
  onPickTopic,
  onPickDesign,
  onPickRun,
}: Props) {
  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState(0);
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (open) {
      setQuery("");
      setCursor(0);
      // Tick after mount so the input is in the DOM.
      setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [open]);

  const items = useMemo<Array<{ item: Item; label: string; sub: string }>>(
    () => {
      const all: Array<{ item: Item; label: string; sub: string }> = [];
      for (const t of topics)
        all.push({
          item: { kind: "topic", topic: t },
          label: t.name,
          sub: `topic · ${t.source_count} sources`,
        });
      for (const d of designs)
        all.push({
          item: { kind: "design", design: d },
          label: d.name,
          sub: `design · ${d.description.slice(0, 80)}`,
        });
      for (const r of runs)
        all.push({
          item: { kind: "run", run: r },
          label: r.topic_name,
          sub: `${r.design_name} · ${r.articles[0]?.title?.slice(0, 70) ?? ""}`,
        });
      return all;
    },
    [topics, designs, runs],
  );

  const filtered = useMemo(() => {
    if (!query.trim()) return items.slice(0, 30);
    const scored: Array<{ entry: (typeof items)[number]; score: number }> = [];
    for (const e of items) {
      const haystack = `${e.label} ${e.sub}`;
      const s = fuzzyScore(query.trim(), haystack);
      if (s !== null) scored.push({ entry: e, score: s });
    }
    scored.sort((a, b) => a.score - b.score);
    return scored.slice(0, 30).map((s) => s.entry);
  }, [items, query]);

  useEffect(() => {
    if (cursor >= filtered.length) setCursor(Math.max(0, filtered.length - 1));
  }, [filtered.length, cursor]);

  const commit = (e: (typeof filtered)[number] | undefined) => {
    if (!e) return;
    const it = e.item;
    if (it.kind === "topic") onPickTopic(it.topic.slug);
    else if (it.kind === "design") onPickDesign(it.design.slug);
    else onPickRun(it.run);
    onClose();
  };

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 bg-ink-900/60 backdrop-blur-sm flex items-start justify-center pt-[12vh]"
      onClick={onClose}
    >
      <div
        className="w-full max-w-xl bg-ink-800 rounded-2xl shadow-float overflow-hidden ring-1 ring-ink-600/50"
        onClick={(e) => e.stopPropagation()}
      >
        <input
          ref={inputRef}
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setCursor(0);
          }}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") {
              e.preventDefault();
              setCursor((c) => Math.min(filtered.length - 1, c + 1));
            } else if (e.key === "ArrowUp") {
              e.preventDefault();
              setCursor((c) => Math.max(0, c - 1));
            } else if (e.key === "Enter") {
              e.preventDefault();
              commit(filtered[cursor]);
            } else if (e.key === "Escape") {
              e.preventDefault();
              onClose();
            }
          }}
          placeholder="Jump to topic, design, or past run…"
          className="w-full px-5 py-4 bg-transparent text-ink-100 text-base border-b border-ink-700/60 focus:outline-none placeholder:text-ink-400"
        />
        <div className="max-h-[55vh] overflow-y-auto p-2">
          {filtered.length === 0 && (
            <div className="px-4 py-6 text-xs text-ink-300">No matches.</div>
          )}
          {filtered.map((e, i) => {
            const active = i === cursor;
            return (
              <button
                key={`${e.item.kind}-${i}`}
                onMouseEnter={() => setCursor(i)}
                onClick={() => commit(e)}
                className={`w-full text-left px-3 py-2.5 rounded-xl flex items-center gap-3 transition ${
                  active ? "bg-accent/10 ring-1 ring-accent/40" : "hover:bg-ink-700/60"
                }`}
              >
                <span className="text-base w-7 h-7 inline-flex items-center justify-center rounded-lg bg-ink-700/60">
                  {ICON[e.item.kind]}
                </span>
                <span className="flex-1 min-w-0">
                  <div className="text-sm font-medium text-ink-100 truncate">{e.label}</div>
                  <div className="text-[11px] text-ink-300 truncate">{e.sub}</div>
                </span>
                {active && (
                  <span className="text-[10px] uppercase tracking-[0.14em] font-semibold text-accent">
                    ↵
                  </span>
                )}
              </button>
            );
          })}
        </div>
        <div className="px-5 py-2.5 border-t border-ink-700/60 text-[10px] uppercase tracking-[0.14em] font-medium text-ink-400 flex gap-4 bg-ink-700/30">
          <span>↑↓ navigate</span>
          <span>↵ open</span>
          <span>esc close</span>
        </div>
      </div>
    </div>
  );
}

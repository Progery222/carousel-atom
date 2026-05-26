import { useEffect, useState } from "react";
import type { Topic } from "../types";

const EMOJI: Record<string, string> = {
  sports_now: "🔥",
  f1: "🏎",
  nba: "🏀",
  soccer: "⚽",
  ufc: "🥊",
  lifestyle: "✨",
  nfl: "🏈",
  mlb: "⚾",
  tech: "💻",
  nhl: "🏒",
  crypto: "₿",
  movies: "🎬",
  finance: "💰",
  ai: "🤖",
  gaming: "🎮",
  science: "🔬",
  food: "🍔",
  fitness: "💪",
  fashion: "👗",
  celebrity: "⭐",
  music: "🎵",
  tennis: "🎾",
  golf: "⛳",
  boxing: "🥊",
  cricket: "🏏",
  rugby: "🏉",
  nascar: "🏁",
  ncaa_football: "🏈",
  ncaa_basketball: "🏀",
  wwe: "🤼",
  esports: "🎮",
  wnba: "🏀",
  motogp: "🏍",
  olympics: "🥇",
  premier_league: "⚽",
};

interface Props {
  topics: Topic[];
  selected: string | null;
  onSelect: (slug: string) => void;
}

const COLLAPSE_KEY = "carousel-studio:topics-collapsed:v1";

function loadCollapsed(): boolean {
  // Start collapsed by default so the sidebar opens compact — the
  // featured Sports Digest is the primary thing the user touches.
  const v = localStorage.getItem(COLLAPSE_KEY);
  if (v === "expanded") return false;
  if (v === "collapsed") return true;
  return true; // default
}

export function TopicPicker({ topics, selected, onSelect }: Props) {
  const featured = topics.filter((t) => t.featured);
  const regular = topics.filter((t) => !t.featured);

  const [collapsed, setCollapsed] = useState<boolean>(loadCollapsed);

  // If the user picks a non-featured topic via Cmd-K or history while
  // the list is collapsed, auto-expand so they can see the active row.
  useEffect(() => {
    if (collapsed && selected && regular.some((t) => t.slug === selected)) {
      setCollapsed(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected]);

  useEffect(() => {
    localStorage.setItem(COLLAPSE_KEY, collapsed ? "collapsed" : "expanded");
  }, [collapsed]);

  const renderItem = (t: Topic, big = false) => {
    const active = selected === t.slug;
    return (
      <button
        key={t.slug}
        onClick={() => onSelect(t.slug)}
        className={`w-full text-left rounded-xl transition ${
          big ? "px-3 py-3" : "px-3 py-2.5"
        } ${
          active
            ? "bg-accent/10 ring-1 ring-accent/40 shadow-soft"
            : big
              ? "bg-gradient-to-br from-accent/15 to-ink-700/60 hover:from-accent/20 hover:shadow-soft ring-1 ring-accent/20"
              : "bg-ink-700/60 hover:bg-ink-700 hover:shadow-soft"
        }`}
      >
        <div className="flex items-center gap-2.5">
          <span className={`flex items-center justify-center leading-none shrink-0 ${big ? "w-7 h-7 text-2xl" : "w-6 h-6 text-xl"}`}>
            {EMOJI[t.slug] ?? "📰"}
          </span>
          <div className="flex-1 min-w-0">
            <div className={`font-medium truncate ${big ? "text-[15px]" : "text-sm"} ${active ? "text-accent" : "text-ink-100"}`}>
              {t.name}
            </div>
            <div className="text-[11px] text-ink-300 mt-0.5">
              {t.source_count} sources · {t.news_per_carousel} news
            </div>
          </div>
          {active && (
            <span className="w-1.5 h-1.5 rounded-full bg-accent shadow-soft" />
          )}
        </div>
      </button>
    );
  };

  return (
    <div>
      {featured.length > 0 && (
        <div className="mb-4">
          <h3 className="text-[10px] font-semibold uppercase tracking-[0.14em] text-ink-300 mb-3 px-1">
            Digest
          </h3>
          <div className="space-y-1.5">
            {featured.map((t) => renderItem(t, true))}
          </div>
        </div>
      )}

      {regular.length > 0 && (
        <>
          <button
            onClick={() => setCollapsed((c) => !c)}
            className="w-full flex items-center justify-between mb-3 px-1 text-left group"
          >
            <h3 className="text-[10px] font-semibold uppercase tracking-[0.14em] text-ink-300 group-hover:text-ink-100 transition">
              Topics
              <span className="ml-1.5 text-ink-400 normal-case tracking-normal font-normal">
                · {regular.length}
              </span>
            </h3>
            <span
              className={`text-ink-400 group-hover:text-ink-100 transition-transform text-[10px] ${
                collapsed ? "rotate-0" : "rotate-90"
              }`}
              aria-label={collapsed ? "expand" : "collapse"}
            >
              ▶
            </span>
          </button>
          {!collapsed && (
            <div className="space-y-1.5">
              {regular.map((t) => renderItem(t))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

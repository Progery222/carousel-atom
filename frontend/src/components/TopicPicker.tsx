import type { Topic } from "../types";

const EMOJI: Record<string, string> = {
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
};

interface Props {
  topics: Topic[];
  selected: string | null;
  onSelect: (slug: string) => void;
}

export function TopicPicker({ topics, selected, onSelect }: Props) {
  return (
    <div>
      <h3 className="text-[10px] font-semibold uppercase tracking-[0.14em] text-ink-300 mb-3 px-1">
        Topic
      </h3>
      <div className="space-y-1.5">
        {topics.map((t) => {
          const active = selected === t.slug;
          return (
            <button
              key={t.slug}
              onClick={() => onSelect(t.slug)}
              className={`w-full text-left px-3 py-2.5 rounded-xl transition ${
                active
                  ? "bg-accent/10 ring-1 ring-accent/40 shadow-soft"
                  : "bg-ink-700/60 hover:bg-ink-700 hover:shadow-soft"
              }`}
            >
              <div className="flex items-center gap-2.5">
                <span className="w-6 h-6 flex items-center justify-center text-xl leading-none shrink-0">{EMOJI[t.slug] ?? "📰"}</span>
                <div className="flex-1 min-w-0">
                  <div className={`text-sm font-medium truncate ${active ? "text-accent" : "text-ink-100"}`}>
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
        })}
      </div>
    </div>
  );
}

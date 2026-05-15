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
};

interface Props {
  topics: Topic[];
  selected: string | null;
  onSelect: (slug: string) => void;
}

export function TopicPicker({ topics, selected, onSelect }: Props) {
  const featured = topics.filter((t) => t.featured);
  const regular = topics.filter((t) => !t.featured);

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
      <h3 className="text-[10px] font-semibold uppercase tracking-[0.14em] text-ink-300 mb-3 px-1">
        Topic
      </h3>
      <div className="space-y-1.5">
        {regular.map((t) => renderItem(t))}
      </div>
    </div>
  );
}

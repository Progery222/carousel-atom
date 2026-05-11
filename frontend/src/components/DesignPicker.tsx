import type { Design } from "../types";

interface Props {
  designs: Design[];
  selected: string | null;
  onSelect: (slug: string) => void;
}

const ICON: Record<string, string> = {
  tiktok_news: "✦",
  newsflash: "▭",
  viral_roundup: "▼",
  quote_card: "❝",
  premium_light: "◻",
  story_mode: "▷",
  blueprint: "⊞",
};

export function DesignPicker({ designs, selected, onSelect }: Props) {
  return (
    <div>
      <h3 className="text-[10px] font-semibold uppercase tracking-[0.14em] text-ink-300 mb-3 px-1">
        Design
      </h3>
      <div className="space-y-1.5">
        {designs.map((d) => {
          const active = selected === d.slug;
          return (
            <button
              key={d.slug}
              onClick={() => onSelect(d.slug)}
              className={`w-full text-left p-3 rounded-xl transition ${
                active
                  ? "bg-accent/10 ring-1 ring-accent/40 shadow-soft"
                  : "bg-ink-700/60 hover:bg-ink-700 hover:shadow-soft"
              }`}
            >
              <div className="flex items-start gap-2.5">
                <span className={`text-lg leading-none mt-0.5 ${active ? "text-accent" : "text-ink-300"}`}>
                  {ICON[d.slug] ?? "□"}
                </span>
                <div className="flex-1 min-w-0">
                  <div className={`text-sm font-semibold ${active ? "text-accent" : "text-ink-100"}`}>
                    {d.name}
                  </div>
                  <div className="text-[11px] text-ink-300 mt-0.5 leading-snug line-clamp-2">
                    {d.description}
                  </div>
                </div>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}

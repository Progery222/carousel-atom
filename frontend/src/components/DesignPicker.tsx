import { useState } from "react";
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
  seamless: "▬",          // wide horizontal bar — continuous-image format
  quote_tweet: "𝕏",       // X/Twitter glyph — tweet-style design
  highlight_reel: "▶",    // play arrow — sports highlight thumbnail style
  polaroid: "▱",          // tilted parallelogram — polaroid card vibe
};

/** Compact design picker: 3-column grid of icon tiles. Selected tile
 *  expands a small description strip beneath, so we get the visual
 *  density of a toolbar but keep the explanatory copy one click away. */
export function DesignPicker({ designs, selected, onSelect }: Props) {
  const [hovered, setHovered] = useState<string | null>(null);
  const visible = hovered ?? selected;
  const visibleDesign = designs.find((d) => d.slug === visible);

  return (
    <div>
      <h3 className="text-[10px] font-semibold uppercase tracking-[0.14em] text-ink-300 mb-3 px-1">
        Design
      </h3>
      <div className="grid grid-cols-3 gap-1.5">
        {designs.map((d) => {
          const active = selected === d.slug;
          return (
            <button
              key={d.slug}
              onClick={() => onSelect(d.slug)}
              onMouseEnter={() => setHovered(d.slug)}
              onMouseLeave={() => setHovered(null)}
              title={d.name}
              className={`aspect-square rounded-lg transition flex flex-col items-center justify-center gap-1 px-1 py-2 ${
                active
                  ? "bg-accent/10 ring-1 ring-accent/50 shadow-soft"
                  : "bg-ink-700/60 hover:bg-ink-700 hover:shadow-soft"
              }`}
            >
              <span
                className={`text-2xl leading-none ${
                  active ? "text-accent" : "text-ink-200"
                }`}
              >
                {ICON[d.slug] ?? "□"}
              </span>
              <span
                className={`text-[9px] font-medium uppercase tracking-[0.06em] text-center leading-tight truncate w-full ${
                  active ? "text-accent" : "text-ink-300"
                }`}
              >
                {/* show the LAST word: "Quote Card" → "Card", "Quote Tweet" → "Tweet",
                    "Highlight Reel" → "Reel" — more distinctive than first-word truncation
                    when several designs share a leading word. */}
                {d.name.split(" ").pop() ?? d.name}
              </span>
            </button>
          );
        })}
      </div>

      {/* Inline description: shows whichever design is hovered, falls
          back to the selected one. Reserved height (h-16) so the
          sidebar doesn't jitter when hovering between tiles. */}
      <div className="mt-2 px-2 h-16 overflow-hidden">
        {visibleDesign && (
          <>
            <div className="text-[11px] font-semibold text-ink-100 truncate">
              {visibleDesign.name}
            </div>
            <div className="text-[10px] text-ink-300 leading-snug line-clamp-3">
              {visibleDesign.description}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

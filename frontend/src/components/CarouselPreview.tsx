import { absSlideUrl } from "../api";
import type { Article, Slide } from "../types";

type Layout = "strip" | "grid";

interface Props {
  slides: Slide[];
  articles?: Article[];
  loading: boolean;
  empty: boolean;
  layout?: Layout;
  onLayoutChange?: (next: Layout) => void;
  lockedUrls?: Set<string>;
  busySlot?: number | null;
  onToggleLock?: (url: string) => void;
  onRerollSlot?: (index: number) => void;
  onEditSlot?: (index: number) => void;
}

export function CarouselPreview({
  slides,
  articles,
  loading,
  empty,
  layout = "strip",
  onLayoutChange,
  lockedUrls,
  busySlot,
  onToggleLock,
  onRerollSlot,
  onEditSlot,
}: Props) {
  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center text-ink-300 text-sm gap-2">
        <span className="inline-block w-2 h-2 rounded-full bg-accent animate-pulse" />
        Generating — fetching news, rendering slides…
      </div>
    );
  }
  if (empty) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center text-center px-6">
        <div className="w-16 h-16 rounded-2xl bg-accent/10 flex items-center justify-center text-2xl mb-4">
          ✨
        </div>
        <p className="text-base font-semibold text-ink-100 mb-1">Ready when you are</p>
        <p className="text-sm text-ink-300">
          Pick a topic and design, then hit{" "}
          <span className="mx-1 px-2 py-0.5 rounded-md bg-accent text-white text-xs font-semibold">
            Generate
          </span>
        </p>
      </div>
    );
  }
  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      <div className="flex items-center justify-end gap-1 px-8 pt-4 pb-2">
        <LayoutToggle layout={layout} onChange={onLayoutChange} />
      </div>
      {layout === "strip" ? (
        <div className="flex-1 overflow-x-auto overflow-y-hidden">
          <div className="flex gap-5 px-8 py-4 min-w-max h-full items-center">
            {slides.map((s) => {
              const url = articles?.[s.index]?.url ?? "";
              return (
                <SlideCard
                  key={s.index}
                  s={s}
                  count={slides.length}
                  size="lg"
                  locked={!!url && lockedUrls?.has(url)}
                  busy={busySlot === s.index}
                  onToggleLock={url && onToggleLock ? () => onToggleLock(url) : undefined}
                  onReroll={onRerollSlot ? () => onRerollSlot(s.index) : undefined}
                  onEdit={onEditSlot ? () => onEditSlot(s.index) : undefined}
                />
              );
            })}
          </div>
        </div>
      ) : (
        <div className="flex-1 overflow-y-auto px-8 py-4">
          <div className="grid gap-5"
               style={{ gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))" }}>
            {slides.map((s) => {
              const url = articles?.[s.index]?.url ?? "";
              return (
                <SlideCard
                  key={s.index}
                  s={s}
                  count={slides.length}
                  size="md"
                  locked={!!url && lockedUrls?.has(url)}
                  busy={busySlot === s.index}
                  onToggleLock={url && onToggleLock ? () => onToggleLock(url) : undefined}
                  onReroll={onRerollSlot ? () => onRerollSlot(s.index) : undefined}
                  onEdit={onEditSlot ? () => onEditSlot(s.index) : undefined}
                />
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

function LayoutToggle({
  layout,
  onChange,
}: {
  layout: Layout;
  onChange?: (next: Layout) => void;
}) {
  if (!onChange) return null;
  return (
    <div className="inline-flex p-1 rounded-lg bg-ink-800 text-[10px] uppercase tracking-[0.14em] font-semibold shadow-soft">
      {(["strip", "grid"] as Layout[]).map((opt) => (
        <button
          key={opt}
          onClick={() => onChange(opt)}
          className={`px-3 py-1 rounded-md transition ${
            layout === opt
              ? "bg-accent text-white shadow-soft"
              : "text-ink-300 hover:text-ink-100"
          }`}
        >
          {opt}
        </button>
      ))}
    </div>
  );
}

function SlideCard({
  s,
  count,
  size,
  locked,
  busy,
  onToggleLock,
  onReroll,
  onEdit,
}: {
  s: Slide;
  count: number;
  size: "md" | "lg";
  locked?: boolean;
  busy?: boolean;
  onToggleLock?: () => void;
  onReroll?: () => void;
  onEdit?: () => void;
}) {
  const dims = size === "lg" ? { width: 270, height: 360 } : { width: "100%", aspectRatio: "3 / 4" as const };
  return (
    <div
      className={`group relative rounded-2xl overflow-hidden transition-all duration-200 hover:-translate-y-1 ${
        locked
          ? "ring-2 ring-accent shadow-card"
          : "shadow-card hover:shadow-float"
      }`}
      style={dims}
    >
      <img
        src={absSlideUrl(s.url)}
        alt={`slide ${s.index + 1}`}
        className={`w-full h-full object-cover transition ${busy ? "opacity-40 blur-sm" : ""}`}
        draggable={false}
      />
      <div className="absolute top-2.5 left-2.5 px-2 py-0.5 bg-black/60 backdrop-blur-sm text-white text-[10px] font-mono font-semibold rounded-md">
        {s.index + 1} / {count}
      </div>
      {locked && !busy && (
        <div className="absolute top-2.5 right-2.5 px-2 py-0.5 bg-accent text-white text-[10px] font-semibold rounded-md shadow-soft"
             title="Locked — won't be replaced on re-roll">
          🔒 LOCKED
        </div>
      )}
      {busy && (
        <div className="absolute inset-0 flex items-center justify-center text-white text-xs uppercase tracking-[0.14em] font-semibold bg-black/40 backdrop-blur-[1px]">
          Re-rolling…
        </div>
      )}
      {(onToggleLock || onReroll || onEdit) && !busy && (
        <div className="absolute inset-x-0 bottom-0 px-2.5 pb-2.5 pt-8 flex justify-center gap-1.5 opacity-0 group-hover:opacity-100 transition bg-gradient-to-t from-black/70 to-transparent">
          {onEdit && (
            <SlideAction
              onClick={onEdit}
              title="Edit headline (E)"
              icon="✏"
            />
          )}
          {onToggleLock && (
            <SlideAction
              onClick={onToggleLock}
              title={locked ? "Unlock — allow re-roll" : "Lock — keep on re-roll"}
              icon={locked ? "🔓" : "🔒"}
              active={locked}
            />
          )}
          {onReroll && !locked && (
            <SlideAction
              onClick={onReroll}
              title="Re-roll just this slide"
              icon="🔄"
            />
          )}
        </div>
      )}
    </div>
  );
}

function SlideAction({
  icon,
  title,
  active,
  onClick,
}: {
  icon: string;
  title: string;
  active?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      title={title}
      className={`w-9 h-9 inline-flex items-center justify-center text-sm rounded-lg shadow-card transition hover:-translate-y-px ${
        active
          ? "bg-accent text-white"
          : "bg-white/95 text-ink-100 hover:bg-white"
      }`}
    >
      {icon}
    </button>
  );
}

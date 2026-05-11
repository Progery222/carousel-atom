import { useEffect, useState } from "react";
import { API_BASE } from "../api";

interface Health {
  ok: boolean;
  designs: string[];
  topics: string[];
  deliveries: string[];
  llm_enabled: boolean;
  stats: Record<string, { seen: number; posts: number; last_post: number | null }>;
}

interface Props {
  topic: string | null;
}

export function StatusPill({ topic }: Props) {
  const [health, setHealth] = useState<Health | null>(null);

  useEffect(() => {
    let alive = true;
    const load = () =>
      fetch(`${API_BASE}/health`)
        .then((r) => (r.ok ? r.json() : null))
        .then((h) => {
          if (alive) setHealth(h);
        })
        .catch(() => {
          if (alive) setHealth(null);
        });
    load();
    const t = setInterval(load, 30_000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  if (!health) {
    return (
      <span className="inline-flex items-center gap-1.5 text-[10px] uppercase tracking-[0.14em] font-semibold text-accent-red">
        <span className="w-1.5 h-1.5 rounded-full bg-accent-red" />
        backend offline
      </span>
    );
  }
  const stats = topic ? health.stats[topic] : undefined;
  const last = stats?.last_post
    ? new Date(stats.last_post * 1000).toLocaleString(undefined, {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "never";

  return (
    <div className="flex items-center gap-3 text-[10px] uppercase tracking-[0.14em] font-medium text-ink-300">
      <span className="inline-flex items-center gap-1.5 text-emerald-500 font-semibold">
        <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 shadow-[0_0_8px_rgb(16_185_129_/_0.8)]" />
        live
      </span>
      {stats && (
        <span title="seen articles · posts" className="hidden md:inline">
          {stats.seen} seen · {stats.posts} posts
        </span>
      )}
      {stats && <span title="last delivery" className="hidden md:inline">last {last}</span>}
      {health.llm_enabled && (
        <span className="px-2 py-0.5 rounded-md bg-accent/15 text-accent font-semibold">
          llm
        </span>
      )}
    </div>
  );
}

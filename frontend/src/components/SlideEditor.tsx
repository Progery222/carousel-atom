import { useState, useEffect } from "react";
import { uploadImage } from "../api";
import type { Article } from "../types";

interface Props {
  articles: Article[];
  onCancel: () => void;
  /** Called with an updated article list. Implementation re-renders the carousel. */
  onApply: (next: Article[]) => Promise<void> | void;
  busy?: boolean;
}

/** Image field with drag-n-drop upload AND URL paste. */
function ImageField({
  value,
  onChange,
}: {
  value: string;
  onChange: (url: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [drag, setDrag] = useState(false);

  const onFile = async (file: File) => {
    if (!file.type.startsWith("image/")) {
      setError("Not an image");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const { url } = await uploadImage(file);
      onChange(url);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setDrag(true);
      }}
      onDragLeave={() => setDrag(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDrag(false);
        const file = e.dataTransfer?.files?.[0];
        if (file) onFile(file);
      }}
      className={`relative rounded ${
        drag ? "ring-2 ring-accent" : ""
      }`}
    >
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full px-2 py-1.5 text-xs font-mono bg-ink-800 border border-ink-600 rounded text-ink-300 focus:border-accent focus:outline-none pr-16"
        placeholder="https://… or drag-drop an image"
      />
      <label className="absolute right-1 top-1 bottom-1 flex items-center px-2 text-[10px] uppercase tracking-wider bg-ink-700 border border-ink-600 rounded text-ink-300 hover:text-ink-100 hover:border-ink-400 cursor-pointer">
        {busy ? "…" : "Upload"}
        <input
          type="file"
          accept="image/*"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) onFile(f);
            e.target.value = "";
          }}
        />
      </label>
      {error && (
        <div className="text-[10px] text-accent-red mt-1">{error}</div>
      )}
    </div>
  );
}


/** Article-level editor: rename, replace image URL, reorder, drop. */
export function SlideEditor({ articles, onCancel, onApply, busy }: Props) {
  const [draft, setDraft] = useState<Article[]>(() =>
    articles.map((a) => ({ ...a })),
  );

  useEffect(() => {
    setDraft(articles.map((a) => ({ ...a })));
  }, [articles]);

  const update = (i: number, patch: Partial<Article>) =>
    setDraft((d) => d.map((a, idx) => (idx === i ? { ...a, ...patch } : a)));

  const move = (i: number, dir: -1 | 1) => {
    const j = i + dir;
    if (j < 0 || j >= draft.length) return;
    setDraft((d) => {
      const next = [...d];
      [next[i], next[j]] = [next[j], next[i]];
      return next;
    });
  };

  const remove = (i: number) =>
    setDraft((d) => d.filter((_, idx) => idx !== i));

  return (
    <div className="border-t border-ink-700 bg-ink-800 p-4 space-y-3 max-h-[60vh] overflow-y-auto">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-ink-300">
          Edit articles · {draft.length}
        </h3>
        <div className="flex gap-2">
          <button
            onClick={onCancel}
            className="px-3 py-1.5 text-xs bg-ink-700 border border-ink-600 text-ink-100 rounded hover:border-ink-400"
          >
            Cancel
          </button>
          <button
            disabled={busy || draft.length === 0}
            onClick={() => onApply(draft)}
            className="px-3 py-1.5 text-xs bg-accent text-white rounded font-semibold hover:bg-accent/90 disabled:opacity-60"
          >
            {busy ? "Re-rendering…" : "Apply & re-render"}
          </button>
        </div>
      </div>

      <div className="space-y-2">
        {draft.map((a, i) => (
          <div
            key={`${a.url}-${i}`}
            className="rounded-lg border border-ink-600 bg-ink-900 p-3 space-y-2"
          >
            <div className="flex items-start gap-2">
              <div className="flex flex-col gap-1 pt-1">
                <button
                  onClick={() => move(i, -1)}
                  disabled={i === 0}
                  className="px-1.5 py-0.5 text-[10px] rounded bg-ink-700 border border-ink-600 disabled:opacity-30"
                  title="Move up"
                >
                  ↑
                </button>
                <button
                  onClick={() => move(i, 1)}
                  disabled={i === draft.length - 1}
                  className="px-1.5 py-0.5 text-[10px] rounded bg-ink-700 border border-ink-600 disabled:opacity-30"
                  title="Move down"
                >
                  ↓
                </button>
              </div>

              <div className="flex-1 min-w-0 space-y-2">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[10px] uppercase tracking-wider text-ink-300">
                    #{i + 1} · {a.source}
                  </span>
                  <button
                    onClick={() => remove(i)}
                    className="text-[10px] text-accent-red hover:underline"
                    title="Remove from carousel"
                  >
                    remove
                  </button>
                </div>

                <input
                  value={a.title}
                  onChange={(e) => update(i, { title: e.target.value })}
                  className="w-full px-2 py-1.5 text-sm bg-ink-800 border border-ink-600 rounded text-ink-100 focus:border-accent focus:outline-none"
                  placeholder="Headline"
                />

                <ImageField
                  value={a.image_url ?? ""}
                  onChange={(url) => update(i, { image_url: url })}
                />

                <textarea
                  value={a.description ?? ""}
                  onChange={(e) => update(i, { description: e.target.value })}
                  rows={2}
                  className="w-full px-2 py-1.5 text-xs bg-ink-800 border border-ink-600 rounded text-ink-200 focus:border-accent focus:outline-none resize-y"
                  placeholder="Description (used by some designs)"
                />
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

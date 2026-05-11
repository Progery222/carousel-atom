import { useEffect, useRef, useState } from "react";
import { rewriteHeadline, type RewriteStyle } from "../api";
import type { Article } from "../types";

interface Props {
  article: Article;
  index: number;
  total: number;
  llmEnabled: boolean;
  onCancel: () => void;
  onSave: (next: Article) => Promise<void> | void;
}

const STYLES: Array<{ key: RewriteStyle; label: string; hint: string }> = [
  { key: "punchier", label: "Punchier", hint: "tighter, fewer words" },
  { key: "factual", label: "Factual", hint: "drop hype" },
  { key: "hook", label: "Hook", hint: "ends on curiosity" },
  { key: "translate_ru", label: "RU", hint: "перевод" },
];

/** Single-slide quick editor: title + description + ✨ LLM rewrite menu.
 *  Opens as a centered modal; commits via /render/edit upstream. */
export function SlideQuickEdit({
  article,
  index,
  total,
  llmEnabled,
  onCancel,
  onSave,
}: Props) {
  const [title, setTitle] = useState(article.title);
  const [description, setDescription] = useState(article.description ?? "");
  const [rewriting, setRewriting] = useState<RewriteStyle | null>(null);
  const [saving, setSaving] = useState(false);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    setTimeout(() => inputRef.current?.focus(), 0);
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCancel();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onCancel]);

  const onAi = async (style: RewriteStyle) => {
    if (!title.trim()) return;
    setRewriting(style);
    try {
      const res = await rewriteHeadline(title, style);
      if (res.title) setTitle(res.title);
    } finally {
      setRewriting(null);
    }
  };

  const submit = async () => {
    setSaving(true);
    try {
      await onSave({
        ...article,
        title: title.trim(),
        description: description.trim(),
      });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 bg-ink-900/60 backdrop-blur-sm flex items-start justify-center pt-[12vh]"
      onClick={onCancel}
    >
      <div
        className="w-full max-w-lg bg-ink-800 rounded-2xl shadow-float ring-1 ring-ink-600/50 overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-5 py-3 border-b border-ink-700/60">
          <div className="text-[11px] uppercase tracking-[0.14em] font-semibold text-ink-300">
            Slide {index + 1} <span className="text-ink-400 font-normal">/ {total} ·</span> {article.source}
          </div>
          <button
            onClick={onCancel}
            className="text-ink-300 hover:text-ink-100 text-lg"
            aria-label="close"
          >
            ×
          </button>
        </div>

        <div className="p-5 space-y-4">
          <div>
            <label className="text-[10px] uppercase tracking-[0.14em] font-semibold text-ink-300 block mb-1.5">
              Headline
            </label>
            <textarea
              ref={inputRef}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                  e.preventDefault();
                  submit();
                }
              }}
              rows={3}
              className="w-full px-3.5 py-2.5 text-sm bg-ink-700/50 rounded-xl text-ink-100 focus:bg-ink-700 focus:outline-none focus:ring-2 focus:ring-accent/40 resize-none transition"
            />
          </div>

          <div>
            <div className="flex items-center gap-2 mb-2">
              <label className="text-[10px] uppercase tracking-[0.14em] font-semibold text-ink-300">
                ✨ LLM rewrite
              </label>
              {!llmEnabled && (
                <span className="text-[10px] text-ink-400 normal-case tracking-normal">
                  set LLM_API_KEY to enable
                </span>
              )}
            </div>
            <div className="flex flex-wrap gap-1.5">
              {STYLES.map((s) => {
                const active = rewriting === s.key;
                return (
                  <button
                    key={s.key}
                    onClick={() => onAi(s.key)}
                    disabled={!llmEnabled || rewriting !== null}
                    title={s.hint}
                    className={`px-3 py-1.5 text-[11px] font-medium rounded-lg transition ${
                      active
                        ? "bg-accent text-white shadow-soft"
                        : "bg-ink-700/60 text-ink-200 hover:bg-ink-700 hover:text-ink-100 disabled:opacity-40 disabled:hover:bg-ink-700/60"
                    }`}
                  >
                    {active ? "…" : s.label}
                  </button>
                );
              })}
            </div>
          </div>

          <div>
            <label className="text-[10px] uppercase tracking-[0.14em] font-semibold text-ink-300 block mb-1.5">
              Description <span className="font-normal text-ink-400 normal-case tracking-normal">(used by some designs)</span>
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={3}
              className="w-full px-3.5 py-2.5 text-xs bg-ink-700/50 rounded-xl text-ink-200 focus:bg-ink-700 focus:outline-none focus:ring-2 focus:ring-accent/40 resize-y transition"
              placeholder="Optional body text."
            />
          </div>
        </div>

        <div className="px-5 py-3 border-t border-ink-700/60 bg-ink-700/20 flex items-center justify-between">
          <span className="text-[10px] uppercase tracking-[0.14em] font-medium text-ink-400">⌘↵ save · Esc close</span>
          <div className="flex gap-2">
            <button
              onClick={onCancel}
              className="px-3 py-2 text-xs font-medium bg-ink-700 text-ink-200 rounded-lg hover:bg-ink-600 hover:text-ink-100 transition"
            >
              Cancel
            </button>
            <button
              onClick={submit}
              disabled={saving || !title.trim()}
              className="px-4 py-2 text-xs bg-accent text-white rounded-lg font-semibold shadow-soft hover:shadow-card hover:-translate-y-px transition disabled:opacity-60 disabled:translate-y-0 disabled:hover:shadow-soft"
            >
              {saving ? "Re-rendering…" : "Save & re-render"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

import { useEffect, useMemo, useState } from "react";
import {
  API_BASE,
  fetchDesigns,
  fetchTopics,
  rerenderEdited,
  rerenderPartial,
  renderCarousel,
  RenderError,
  resetSeen,
} from "./api";
import { CandidatePanel } from "./components/CandidatePanel";
import { CarouselPreview } from "./components/CarouselPreview";
import { CmdK } from "./components/CmdK";
import { DesignPicker } from "./components/DesignPicker";
import { ExportPanel } from "./components/ExportPanel";
import { HistoryPanel } from "./components/HistoryPanel";
import { SlideEditor } from "./components/SlideEditor";
import { SlideQuickEdit } from "./components/SlideQuickEdit";
import { StatusPill } from "./components/StatusPill";
import { ThemeToggle } from "./components/ThemeToggle";
import { Toast } from "./components/Toast";
import { TopicPicker } from "./components/TopicPicker";
import type {
  Article,
  Design,
  LocalRun,
  RenderResult,
  Topic,
} from "./types";

const HISTORY_KEY = "carousel-studio:runs:v1";
const LAYOUT_KEY = "carousel-studio:layout:v1";
const THEME_KEY = "carousel-studio:theme:v1";
const HISTORY_LIMIT = 24;

/** Format an error from `renderCarousel`/`rerenderEdited`/etc. into a
 *  user-readable toast. For RenderError with diagnostics, build a
 *  breakdown like "no_articles · raw=87, fresh=64, kept=12 · seen=23,
 *  no-image=41" so the user can act on it. */
function formatRenderError(e: unknown): string {
  if (e instanceof RenderError) {
    const d = e.diagnostics;
    if (!d) return `${e.status}: ${e.message}`;
    const reasons = Object.entries(d.drop_reasons ?? {})
      .sort(([, a], [, b]) => b - a)
      .slice(0, 4)
      .map(([k, v]) => `${k}=${v}`)
      .join(", ");
    const counts = `raw=${d.raw}, fresh=${d.fresh}, kept=${d.after_enrich}`;
    return reasons
      ? `${e.status} · ${counts} · ${reasons}`
      : `${e.status} · ${counts}`;
  }
  return e instanceof Error ? e.message : String(e);
}

type Layout = "strip" | "grid";
type Theme = "dark" | "light";

function loadTheme(): Theme {
  const v = localStorage.getItem(THEME_KEY);
  return v === "dark" ? "dark" : "light";
}

function loadHistory(): LocalRun[] {
  try {
    const raw = localStorage.getItem(HISTORY_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as LocalRun[];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function saveHistory(runs: LocalRun[]) {
  try {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(runs.slice(0, HISTORY_LIMIT)));
  } catch {
    /* quota exceeded — best-effort */
  }
}

function loadLayout(): Layout {
  return (localStorage.getItem(LAYOUT_KEY) as Layout) ?? "strip";
}

export default function App() {
  const [topics, setTopics] = useState<Topic[]>([]);
  const [designs, setDesigns] = useState<Design[]>([]);
  const [topic, setTopic] = useState<string | null>(null);
  const [design, setDesign] = useState<string | null>(null);

  const [result, setResult] = useState<RenderResult | null>(null);
  const [caption, setCaption] = useState<string>("");
  const [editing, setEditing] = useState(false);
  const [layout, setLayout] = useState<Layout>(loadLayout);

  const [loading, setLoading] = useState(false);
  const [batchProgress, setBatchProgress] = useState<{
    done: number;
    total: number;
    label?: string;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [history, setHistory] = useState<LocalRun[]>(() => loadHistory());
  const [pickerOpen, setPickerOpen] = useState(false);
  const [cmdkOpen, setCmdkOpen] = useState(false);
  const [theme, setTheme] = useState<Theme>(loadTheme);
  const [lockedUrls, setLockedUrls] = useState<Set<string>>(() => new Set());
  const [busySlot, setBusySlot] = useState<number | null>(null);
  const [quickEditIndex, setQuickEditIndex] = useState<number | null>(null);
  const [llmEnabled, setLlmEnabled] = useState(false);

  // Reflect theme on the document root so the CSS-variable palette
  // swaps without component-level branching.
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem(THEME_KEY, theme);
  }, [theme]);

  useEffect(() => {
    Promise.all([fetchTopics(), fetchDesigns()])
      .then(([t, d]) => {
        setTopics(t);
        setDesigns(d);
        if (t.length) setTopic(t[0].slug);
        if (d.length) setDesign(d[0].slug);
      })
      .catch((e) => setError(String(e)));
    // Pull /health once to know whether LLM rewrite buttons should be live.
    fetch(`${API_BASE}/health`)
      .then((r) => (r.ok ? r.json() : null))
      .then((h) => h && setLlmEnabled(Boolean(h.llm_enabled)))
      .catch(() => {});
  }, []);

  useEffect(() => {
    saveHistory(history);
  }, [history]);

  useEffect(() => {
    localStorage.setItem(LAYOUT_KEY, layout);
  }, [layout]);

  const topicName = useMemo(
    () => topics.find((t) => t.slug === topic)?.name ?? topic ?? "",
    [topics, topic],
  );
  const designName = useMemo(
    () => designs.find((d) => d.slug === design)?.name ?? design ?? "",
    [designs, design],
  );

  const pushHistory = (r: RenderResult, capt: string) => {
    const t = topics.find((x) => x.slug === r.topic);
    const d = designs.find((x) => x.slug === r.design);
    const entry: LocalRun = {
      run_id: r.run_id,
      topic: r.topic,
      topic_name: t?.name ?? r.topic,
      design: r.design,
      design_name: d?.name ?? r.design,
      created_at: Date.now(),
      caption: capt,
      slides: r.slides,
      articles: r.articles,
    };
    setHistory((prev) => [entry, ...prev.filter((p) => p.run_id !== entry.run_id)]);
  };

  const generate = async () => {
    if (!topic || !design) return;
    setLoading(true);
    setError(null);
    setEditing(false);
    try {
      // If the user has locked some slides in the current result, do a
      // partial re-roll: keep the locks, fetch fresh stories for the
      // unlocked slots. Falls back to a full fresh render otherwise.
      const lockedInCurrent =
        result?.articles.filter((a) => lockedUrls.has(a.url)) ?? [];
      if (result && lockedInCurrent.length > 0) {
        const articles: Array<Article | null> = result.articles.map((a) =>
          lockedUrls.has(a.url) ? a : null,
        );
        const r = await rerenderPartial(topic, design, articles);
        setResult(r);
        setCaption(r.caption);
        pushHistory(r, r.caption);
      } else {
        const r = await renderCarousel(topic, design, false);
        setResult(r);
        setCaption(r.caption);
        pushHistory(r, r.caption);
      }
    } catch (e) {
      setError(formatRenderError(e));
    } finally {
      setLoading(false);
    }
  };

  const rerollSlot = async (index: number) => {
    if (!topic || !design || !result) return;
    setBusySlot(index);
    setError(null);
    try {
      const articles: Array<Article | null> = result.articles.map((a, i) =>
        i === index ? null : a,
      );
      const r = await rerenderPartial(topic, design, articles);
      setResult(r);
      setCaption(r.caption);
      pushHistory(r, r.caption);
    } catch (e) {
      setError(formatRenderError(e));
    } finally {
      setBusySlot(null);
    }
  };

  const toggleLock = (url: string) => {
    setLockedUrls((prev) => {
      const next = new Set(prev);
      if (next.has(url)) next.delete(url);
      else next.add(url);
      return next;
    });
  };

  const generateBatch = async (count: number) => {
    if (!topic || !design) return;
    setError(null);
    setEditing(false);
    setBatchProgress({ done: 0, total: count });
    try {
      for (let i = 0; i < count; i++) {
        const r = await renderCarousel(topic, design, true);
        setResult(r);
        setCaption(r.caption);
        pushHistory(r, r.caption);
        setBatchProgress({ done: i + 1, total: count });
      }
    } catch (e) {
      setError(formatRenderError(e));
    } finally {
      setBatchProgress(null);
    }
  };

  // Render one carousel per topic (current design) sequentially.
  // Pushes each into history; the final one stays on screen.
  const generateAllTopics = async () => {
    if (!design || topics.length === 0) return;
    setError(null);
    setEditing(false);
    setBatchProgress({ done: 0, total: topics.length, label: topics[0].name });
    try {
      for (let i = 0; i < topics.length; i++) {
        const t = topics[i];
        setBatchProgress({ done: i, total: topics.length, label: t.name });
        setTopic(t.slug);
        const r = await renderCarousel(t.slug, design, true);
        setResult(r);
        setCaption(r.caption);
        pushHistory(r, r.caption);
        setBatchProgress({ done: i + 1, total: topics.length, label: t.name });
      }
    } catch (e) {
      setError(formatRenderError(e));
    } finally {
      setBatchProgress(null);
    }
  };

  const applyEdits = async (next: Article[]) => {
    if (!topic || !design) return;
    setLoading(true);
    setError(null);
    try {
      const r = await rerenderEdited(topic, design, next);
      setResult(r);
      setCaption(r.caption);
      pushHistory(r, r.caption);
      setEditing(false);
    } catch (e) {
      setError(formatRenderError(e));
    } finally {
      setLoading(false);
    }
  };

  const restoreFromHistory = (run: LocalRun) => {
    setTopic(run.topic);
    setDesign(run.design);
    setResult({
      status: "ok",
      run_id: run.run_id,
      topic: run.topic,
      design: run.design,
      caption: run.caption,
      articles: run.articles,
      slides: run.slides,
    });
    setCaption(run.caption);
    setEditing(false);
  };

  const onResetSeen = async () => {
    if (!topic) return;
    if (!confirm(`Reset seen-store for "${topicName}"? Old stories will be eligible again.`))
      return;
    try {
      const { deleted } = await resetSeen(topic);
      setError(`Cleared ${deleted} entries from "${topicName}".`);
    } catch (e) {
      setError(formatRenderError(e));
    }
  };

  // ── Hotkeys ──────────────────────────────────────────────────────────────
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tgt = e.target as HTMLElement | null;
      const inField =
        !!tgt &&
        (tgt.tagName === "INPUT" ||
          tgt.tagName === "TEXTAREA" ||
          (tgt as HTMLElement).isContentEditable);

      // Cmd/Ctrl-K opens the palette from anywhere outside text fields.
      // Inside a field (caption textarea, slide-editor inputs) we let the
      // keystroke through — the user is typing, not navigating. Once the
      // palette IS open we still listen so Cmd+K can dismiss it even from
      // its own search input.
      if ((e.key === "k" || e.key === "K") && (e.metaKey || e.ctrlKey)) {
        if (inField && !cmdkOpen) return;
        e.preventDefault();
        setCmdkOpen((v) => !v);
        return;
      }

      if (inField) return;

      if (e.key === "g" || e.key === "G") {
        e.preventDefault();
        if (!loading && !batchProgress) generate();
      } else if (e.key === "e" || e.key === "E") {
        if (result) {
          e.preventDefault();
          setEditing((v) => !v);
        }
      } else if (e.key === "b" || e.key === "B") {
        if (!loading && !batchProgress) {
          e.preventDefault();
          generateBatch(3);
        }
      } else if (e.key === "a" || e.key === "A") {
        if (!loading && !batchProgress) {
          e.preventDefault();
          generateAllTopics();
        }
      } else if (e.key === "v" || e.key === "V") {
        e.preventDefault();
        setLayout((l) => (l === "strip" ? "grid" : "strip"));
      } else if (e.key === "p" || e.key === "P") {
        if (topic) {
          e.preventDefault();
          setPickerOpen((v) => !v);
        }
      } else if (e.key === "Escape") {
        if (cmdkOpen) setCmdkOpen(false);
        else if (pickerOpen) setPickerOpen(false);
        else if (editing) setEditing(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [result, loading, batchProgress, topic, design, cmdkOpen]);

  return (
    <div className="h-full flex bg-ink-900">
      <aside className="w-80 bg-ink-800 flex flex-col shadow-card">
        <div className="px-6 pt-7 pb-5">
          <div className="flex items-center gap-2.5">
            <span className="inline-flex items-center justify-center w-9 h-9 rounded-xl bg-accent text-white text-base font-bold shadow-soft">
              C
            </span>
            <div>
              <h1 className="text-lg font-bold text-ink-100 leading-none">Carousel Studio</h1>
              <p className="text-[11px] text-ink-300 mt-1">News carousels for TikTok</p>
            </div>
          </div>
        </div>
        <div className="flex-1 overflow-y-auto px-5 pb-4 space-y-7">
          <TopicPicker topics={topics} selected={topic} onSelect={setTopic} />
          <DesignPicker designs={designs} selected={design} onSelect={setDesign} />
          <div>
            <h3 className="text-[10px] font-semibold uppercase tracking-[0.14em] text-ink-300 mb-3 px-1">
              History
            </h3>
            <HistoryPanel
              runs={history}
              activeRunId={result?.run_id ?? null}
              onSelect={restoreFromHistory}
              onClear={() => setHistory([])}
            />
          </div>
        </div>
        <div className="px-5 pt-4 pb-5 space-y-2 bg-ink-800">
          <button
            onClick={generate}
            disabled={!topic || !design || loading || !!batchProgress}
            title="Generate (G)"
            className="w-full px-4 py-3.5 bg-accent text-white rounded-xl font-semibold text-sm shadow-soft transition hover:shadow-card hover:-translate-y-px hover:bg-accent/95 active:translate-y-0 disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:translate-y-0 disabled:hover:shadow-soft"
          >
            {loading
              ? "Generating…"
              : result
                ? lockedUrls.size > 0
                  ? `Re-roll unlocked · ${lockedUrls.size}🔒`
                  : "Re-roll"
                : "Generate"}
            <span className="ml-2 text-[10px] font-normal opacity-60 tracking-wider">G</span>
          </button>
          <div className="grid grid-cols-2 gap-2">
            <button
              onClick={() => generateBatch(3)}
              disabled={!topic || !design || loading || !!batchProgress}
              title="Generate 3 in a row (B)"
              className="px-3 py-2 bg-ink-700 text-ink-200 rounded-lg text-xs font-medium transition hover:bg-ink-600 hover:text-ink-100 disabled:opacity-40"
            >
              {batchProgress && !batchProgress.label
                ? `Batch ${batchProgress.done}/${batchProgress.total}…`
                : "Batch × 3"}
            </button>
            <button
              onClick={generateAllTopics}
              disabled={!design || loading || !!batchProgress || topics.length === 0}
              title="Generate one carousel per topic (A)"
              className="px-3 py-2 bg-ink-700 text-ink-200 rounded-lg text-xs font-medium transition hover:bg-ink-600 hover:text-ink-100 disabled:opacity-40 truncate"
            >
              {batchProgress && batchProgress.label
                ? `${batchProgress.done}/${batchProgress.total} · ${batchProgress.label}`
                : `All ${topics.length}`}
            </button>
          </div>
          <button
            onClick={() => setPickerOpen(true)}
            disabled={!topic || loading || !!batchProgress}
            title="Pick stories before rendering (P)"
            className="w-full px-3 py-2 text-ink-300 rounded-lg text-xs font-medium transition hover:bg-ink-700 hover:text-ink-100 disabled:opacity-40"
          >
            Pick stories manually
          </button>
          <button
            onClick={onResetSeen}
            disabled={!topic}
            className="w-full pt-1 text-[10px] uppercase tracking-[0.14em] text-ink-400 hover:text-accent-red transition"
          >
            Reset seen · {topicName}
          </button>
        </div>
      </aside>

      <main className="flex-1 flex flex-col overflow-hidden bg-ink-900">
        <header className="h-16 flex items-center px-8 gap-4 bg-ink-900 border-b border-ink-700/60">
          <div className="flex-1 min-w-0">
            {topic && design && (
              <div className="flex items-baseline gap-3 truncate">
                <span className="text-base font-semibold text-ink-100 truncate">{topicName}</span>
                <span className="text-ink-400">/</span>
                <span className="text-sm text-ink-300 truncate">{designName}</span>
                {result && (
                  <span className="ml-2 text-[10px] text-ink-400 font-mono truncate">
                    {result.run_id}
                  </span>
                )}
              </div>
            )}
          </div>
          <ThemeToggle theme={theme} onChange={setTheme} />
          <StatusPill topic={topic} />
        </header>
        <CarouselPreview
          slides={result?.slides ?? []}
          articles={result?.articles}
          loading={loading || !!batchProgress}
          empty={!result}
          layout={layout}
          onLayoutChange={setLayout}
          lockedUrls={lockedUrls}
          busySlot={busySlot}
          onToggleLock={toggleLock}
          onRerollSlot={rerollSlot}
          onEditSlot={(i) => setQuickEditIndex(i)}
        />
        {editing && result ? (
          <SlideEditor
            articles={result.articles}
            busy={loading}
            onCancel={() => setEditing(false)}
            onApply={applyEdits}
          />
        ) : (
          <ExportPanel
            result={result}
            caption={caption}
            onCaptionChange={setCaption}
            onEdit={() => setEditing(true)}
            onError={setError}
          />
        )}
      </main>
      <CandidatePanel
        topic={topic}
        needed={topics.find((t) => t.slug === topic)?.news_per_carousel ?? 5}
        open={pickerOpen}
        onClose={() => setPickerOpen(false)}
        onConfirm={async (selected) => {
          setPickerOpen(false);
          await applyEdits(selected);
        }}
      />
      {quickEditIndex !== null && result && result.articles[quickEditIndex] && (
        <SlideQuickEdit
          article={result.articles[quickEditIndex]}
          index={quickEditIndex}
          total={result.articles.length}
          llmEnabled={llmEnabled}
          onCancel={() => setQuickEditIndex(null)}
          onSave={async (updated) => {
            const next = result.articles.map((a, i) =>
              i === quickEditIndex ? updated : a,
            );
            setQuickEditIndex(null);
            await applyEdits(next);
          }}
        />
      )}
      <CmdK
        open={cmdkOpen}
        onClose={() => setCmdkOpen(false)}
        topics={topics}
        designs={designs}
        runs={history}
        onPickTopic={setTopic}
        onPickDesign={setDesign}
        onPickRun={restoreFromHistory}
      />
      <Toast message={error} onDismiss={() => setError(null)} />
    </div>
  );
}

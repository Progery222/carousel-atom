import { useEffect, useState } from "react";
import JSZip from "jszip";
import { saveAs } from "file-saver";
import { absSlideUrl, deliverRun } from "../api";
import type { RenderResult } from "../types";

interface Props {
  result: RenderResult | null;
  caption: string;
  onCaptionChange: (next: string) => void;
  onEdit: () => void;
  onError: (msg: string) => void;
  onDelivered?: (info: { msg_ids: number[]; runId: string }) => void;
}

export function ExportPanel({
  result,
  caption,
  onCaptionChange,
  onEdit,
  onError,
  onDelivered,
}: Props) {
  const [copied, setCopied] = useState(false);
  const [zipping, setZipping] = useState(false);
  const [delivering, setDelivering] = useState(false);
  const [delivered, setDelivered] = useState(false);
  const [openCaption, setOpenCaption] = useState(false);

  useEffect(() => {
    setOpenCaption(false);
    setDelivered(false);
  }, [result?.run_id]);

  if (!result) return null;

  const downloadZip = async () => {
    setZipping(true);
    let failures = 0;
    try {
      const zip = new JSZip();
      // Pull each slide image fresh from the static endpoint so the ZIP
      // matches whatever is currently in the preview, edits and all.
      // Per-slide try/catch so a single failed fetch doesn't tank the
      // whole ZIP — we count failures and warn the user at the end if
      // anything was skipped.
      await Promise.all(
        result.slides.map(async (s, i) => {
          try {
            const r = await fetch(absSlideUrl(s.url));
            if (!r.ok) throw new Error(`http ${r.status}`);
            const blob = await r.blob();
            zip.file(`slide_${i + 1}.png`, blob);
          } catch (err) {
            failures += 1;
            console.warn("ZIP: slide", i + 1, "failed:", err);
          }
        }),
      );
      zip.file("caption.txt", caption);
      const blob = await zip.generateAsync({ type: "blob" });
      saveAs(blob, `${result.topic}_${result.design}_${result.run_id}.zip`);
      if (failures > 0) {
        onError(`ZIP saved, but ${failures} of ${result.slides.length} slide(s) were skipped (network error).`);
      }
    } catch (e) {
      onError(`Failed to package ZIP: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setZipping(false);
    }
  };

  const copyCaption = async () => {
    await navigator.clipboard.writeText(caption);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  const sendToTelegram = async () => {
    if (!result) return;
    if (
      !confirm(
        `Post this carousel to the Telegram channel for "${result.topic}"?\n\n` +
          `${result.slides.length} slides + caption (${caption.length} chars).`,
      )
    ) {
      return;
    }
    setDelivering(true);
    try {
      const res = await deliverRun(result.run_id, result.topic, caption);
      if (!res.ok) {
        onError(`Telegram: ${res.message}`);
      } else {
        setDelivered(true);
        onDelivered?.({ msg_ids: res.msg_ids, runId: result.run_id });
      }
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setDelivering(false);
    }
  };

  return (
    <div className="bg-ink-800 px-6 py-5 space-y-3 shadow-card">
      <div className="flex gap-2">
        <button
          onClick={sendToTelegram}
          disabled={delivering || delivered}
          title="Post this carousel to the topic's Telegram channel"
          className="flex-1 px-5 py-3 bg-accent text-white rounded-xl font-semibold text-sm shadow-soft transition hover:shadow-card hover:-translate-y-px hover:bg-accent/95 disabled:opacity-60 disabled:translate-y-0 disabled:hover:shadow-soft"
        >
          {delivering ? "Posting…" : delivered ? "Posted ✓" : "Send to Telegram"}
        </button>
        <button
          onClick={downloadZip}
          disabled={zipping}
          className="px-4 py-3 bg-ink-700 text-ink-200 rounded-xl text-sm font-medium transition hover:bg-ink-600 hover:text-ink-100 disabled:opacity-60"
        >
          {zipping ? "Zipping…" : "ZIP"}
        </button>
        <button
          onClick={onEdit}
          className="px-4 py-3 bg-ink-700 text-ink-200 rounded-xl text-sm font-medium transition hover:bg-ink-600 hover:text-ink-100"
        >
          Edit
        </button>
        <button
          onClick={copyCaption}
          className="px-4 py-3 bg-ink-700 text-ink-200 rounded-xl text-sm font-medium transition hover:bg-ink-600 hover:text-ink-100"
        >
          {copied ? "Copied ✓" : "Copy caption"}
        </button>
      </div>

      <div className="bg-ink-700/40 rounded-xl overflow-hidden">
        <button
          onClick={() => setOpenCaption((o) => !o)}
          className="w-full text-left px-4 py-2.5 text-[11px] uppercase tracking-[0.14em] text-ink-300 cursor-pointer select-none flex items-center justify-between gap-3 hover:text-ink-100 transition"
        >
          <span className="truncate font-semibold">Caption · {result.articles.length} articles</span>
          <CaptionLimits caption={caption} />
          <span className="text-ink-400 text-base leading-none">{openCaption ? "−" : "+"}</span>
        </button>
        {openCaption && (
          <textarea
            value={caption}
            onChange={(e) => onCaptionChange(e.target.value)}
            rows={Math.min(18, Math.max(6, caption.split("\n").length + 1))}
            className="w-full p-4 text-xs text-ink-100 font-mono bg-ink-900/60 focus:outline-none resize-y placeholder:text-ink-400"
          />
        )}
      </div>
    </div>
  );
}

function CaptionLimits({ caption }: { caption: string }) {
  // TikTok cap: 2200 chars, 100 hashtags. Instagram: 2200 chars, 30 hashtags.
  const chars = caption.length;
  const hashtags = (caption.match(/#\w+/g) ?? []).length;
  const charLimit = 2200;
  const charsOver = chars > charLimit;
  const hashtagsOverIG = hashtags > 30;
  const hashtagsOverTT = hashtags > 100;
  const cls = (over: boolean) =>
    over ? "text-accent-red" : "text-ink-300";
  return (
    <span className="flex items-center gap-2 text-[10px] tabular-nums normal-case tracking-normal">
      <span className={cls(charsOver)} title={`Instagram & TikTok cap ${charLimit}`}>
        {chars}/{charLimit}
      </span>
      <span className={cls(hashtagsOverIG)} title="Instagram cap 30, TikTok cap 100">
        #{hashtags}{hashtagsOverIG ? (hashtagsOverTT ? " ⚠" : "·IG") : ""}
      </span>
    </span>
  );
}

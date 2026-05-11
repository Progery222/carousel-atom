import { useEffect } from "react";

interface Props {
  message: string | null;
  variant?: "error" | "info";
  onDismiss: () => void;
}

export function Toast({ message, variant = "error", onDismiss }: Props) {
  useEffect(() => {
    if (!message) return;
    const t = setTimeout(onDismiss, variant === "error" ? 6000 : 3500);
    return () => clearTimeout(t);
  }, [message, variant, onDismiss]);

  if (!message) return null;
  const styles =
    variant === "error"
      ? "ring-accent-red/30 bg-accent-red/10 text-accent-red"
      : "ring-accent/30 bg-accent/10 text-accent";

  return (
    <div className="fixed bottom-6 right-6 z-50 max-w-sm">
      <div className={`flex items-start gap-3 rounded-xl ring-1 px-4 py-3 shadow-float backdrop-blur-sm ${styles}`}>
        <span className="flex-1 text-xs leading-relaxed">{message}</span>
        <button
          onClick={onDismiss}
          className="text-base leading-none text-ink-300 hover:text-ink-100"
          aria-label="dismiss"
        >
          ×
        </button>
      </div>
    </div>
  );
}

type Theme = "light" | "dark";

interface Props {
  theme: Theme;
  onChange: (next: Theme) => void;
}

const OPTIONS: Array<{ key: Theme; icon: string; label: string }> = [
  { key: "light", icon: "☀", label: "Light" },
  { key: "dark", icon: "☾", label: "Dark" },
];

export function ThemeToggle({ theme, onChange }: Props) {
  return (
    <div className="inline-flex p-0.5 rounded-lg bg-ink-800 shadow-soft">
      {OPTIONS.map((o) => {
        const active = theme === o.key;
        return (
          <button
            key={o.key}
            onClick={() => onChange(o.key)}
            title={`${o.label} theme`}
            aria-label={`${o.label} theme`}
            aria-pressed={active}
            className={`px-2.5 py-1 rounded-md text-xs font-medium transition ${
              active
                ? "bg-accent text-white shadow-soft"
                : "text-ink-300 hover:text-ink-100"
            }`}
          >
            <span className="mr-1">{o.icon}</span>
            <span className="hidden md:inline">{o.label}</span>
          </button>
        );
      })}
    </div>
  );
}

<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-04 | Updated: 2026-06-04 -->

# components

## Purpose
The reusable, controlled UI building blocks composed by the pages (mainly `StudioPage`). Each component receives state + callbacks as props and owns no global state of its own — pickers, the carousel preview, the slide editors, the modals, and the status/notification widgets all live here.

## Key Files
| File | Description |
|------|-------------|
| `TopicPicker.tsx` | Sidebar dropdown of topics with emoji icons; shows source count + news-per-carousel. |
| `DesignPicker.tsx` | Sidebar dropdown of design templates (icon, name, description); active highlighted in accent. |
| `CarouselPreview.tsx` | Slide gallery in strip or grid layout; per-slide hover actions (lock / reroll / edit); loading skeleton + empty state. |
| `SlideEditor.tsx` | Full article-list editor: reorder (↑↓), remove, edit title/image (upload or URL)/description; Apply re-renders. |
| `SlideQuickEdit.tsx` | Single-slide modal: edit headline + description; LLM rewrite menu (punchier/factual/hook/translate_ru) when enabled; Cmd+Enter saves. |
| `CandidatePanel.tsx` | Modal of ranked candidates from `/preview/articles`; user picks N, then renders from the chosen articles. |
| `ExportPanel.tsx` | Bottom bar: Send to Telegram, ZIP download, Copy Caption, Edit; caption editor with char/hashtag counters. |
| `HistoryPanel.tsx` | Searchable sidebar list of past runs (localStorage `LocalRun[]`); `onSelect` restores full render state. |
| `CmdK.tsx` | Command palette (Cmd/Ctrl+K): fuzzy-search topics/designs/runs; arrows + Enter + Esc. |
| `StatusPill.tsx` | Header badge polling `/health` every ~30s: backend online/offline, seen/post stats, LLM availability. |
| `ThemeToggle.tsx` | Light/dark toggle — sets `<html data-theme>` + localStorage. |
| `Toast.tsx` | Auto-dismiss notification (error 6s / info 3.5s), manual × to close. |

## For AI Agents

### Working In This Directory
- Components are **controlled** — read from props, emit via callbacks; don't reach into `localStorage` or `api.ts` from a leaf component unless that's already its job (e.g. `StatusPill` polls `/health`, `ExportPanel` builds the ZIP).
- Backend calls route through `src/api.ts`; props/shapes come from `src/types.ts`.
- Modal stacking is deliberate: `CmdK` (z-50) sits above `SlideQuickEdit`/`CandidatePanel` (z-40). Preserve the layering when adding modals.
- Page-level hotkeys are owned by `StudioPage` and suppressed inside text inputs — don't add competing global key handlers here.
- ZIP export uses `jszip` + `file-saver` in `ExportPanel`; the image-size limit shown to users (~12 MB) is enforced by the backend, not the client.

### Testing Requirements
- No tests. Verify via `npm run lint`, `npm run build`, and manual browser checks (each interactive state: loading, empty, error, locked slides).

### Common Patterns
- Functional components + Tailwind utility classes; inline SVG icons; CSS-variable theme tokens.

## Dependencies

### Internal
- All consumed by `src/pages/StudioPage.tsx`; typed by `src/types.ts`; data via `src/api.ts`.

### External
- react, jszip + file-saver (ExportPanel), Tailwind.

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->

<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-04 | Updated: 2026-06-04 -->

# src

## Purpose
The application source for the Carousel Studio SPA. Holds the entry point, the router, the two pages, the shared component library, the single backend client, and the shared TypeScript types. State is React hooks + `localStorage`; styling is Tailwind with CSS-variable theming.

## Key Files
| File | Description |
|------|-------------|
| `main.tsx` | React `StrictMode` entry; wraps `<App>` in `BrowserRouter` and hydrates `#root`. |
| `App.tsx` | Router only: `/` → `StudioPage`, `/api-docs` → `ApiDocsPage`. No guards. |
| `api.ts` | **The only module that talks to the backend.** `API_BASE` from `VITE_CAROUSEL_API` (or `localhost:8000`); exports `fetchTopics/Designs`, `renderCarousel`, `rerenderEdited/Partial`, `previewArticles`, `resetSeen`, `deliverRun`, `rewriteHeadline`, `uploadImage`, `fetchPostedRuns`, `fetchDeliveries`; `RenderError` surfaces pipeline diagnostics. |
| `types.ts` | Shared interfaces: `Topic`, `Design`, `Slide`, `Article`, `RenderResult`, `LocalRun` (localStorage model), `PreviewCandidate`, `RenderDiagnostics`. |
| `index.css` | Global Tailwind directives, CSS-variable palette (light/dark), reusable shadow utilities, Inter font stack. |
| `App.css` | Legacy Vite-template hero/logo animation styles; not used by `StudioPage`. |

## Subdirectories
| Directory | Purpose |
|-----------|---------|
| `components/` | Reusable controlled components — pickers, preview, editors, modals, status (see `components/AGENTS.md`) |
| `pages/` | Route-level views: `StudioPage` and `ApiDocsPage` (see `pages/AGENTS.md`) |
| `assets/` | Static images (`hero.png`, `react.svg`, `vite.svg`) — legacy template leftovers, no AGENTS.md |

## For AI Agents

### Working In This Directory
- All new backend calls belong in `api.ts` — don't `fetch` inline from components.
- Shapes are centralized in `types.ts`; reuse/extend them rather than redeclaring inline interfaces.
- `localStorage` keys (`carousel-studio:runs:v1`, `:layout:v1`, `:theme:v1`) are a stable contract — renaming orphans user history/prefs.
- There's no error boundary; surface failures through `RenderError` → the `Toast` component.

### Testing Requirements
- No tests. Run `npm run lint` and `npm run build` (tsc typecheck), then verify in the browser.

### Common Patterns
- `StudioPage` owns the workflow state and passes state + callbacks down; children are controlled and self-contained.
- Theming flips via `<html data-theme>`; modals use fixed z-index layers with backdrop blur.

## Dependencies

### Internal
- `App.tsx` → `pages/`; pages compose `components/`; everything fetches via `api.ts`; all typed by `types.ts`.

### External
- react / react-dom 19, react-router-dom, jszip + file-saver (used by `ExportPanel`), Tailwind.

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->

<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-04 | Updated: 2026-06-04 -->

# pages

## Purpose
The two route-level views of the SPA, wired up in `src/App.tsx`: the main studio workflow and a static public-API documentation page.

## Key Files
| File | Description |
|------|-------------|
| `StudioPage.tsx` | The main hub (route `/`). Owns the workflow state machine and composes the component library: sidebar (pickers + history) → main (carousel preview) → bottom (editor / export). |
| `ApiDocsPage.tsx` | Static docs page (route `/api-docs`). Hardcoded `ENDPOINTS[]` list with curl/JS/Python snippets, error-code legend, rate-limit notes, and links to Swagger/ReDoc/OpenAPI JSON. |

## StudioPage state machine
pick topic (`TopicPicker`) → pick design (`DesignPicker`) → **Generate** → render (`CarouselPreview`) → edit headline (`SlideQuickEdit`) or full articles (`SlideEditor`) → export (`ExportPanel`: ZIP / Telegram / copy caption).

- **Hotkeys**: G generate, E edit, B batch ×3, A all topics, V toggle strip/grid, P pick stories, Esc cancel. Suppressed inside text inputs.
- **localStorage**: `HISTORY_KEY` (run cache, ~24-item cap), `LAYOUT_KEY` (strip/grid), `THEME_KEY`.
- **Locks**: re-roll respects locked slides; unselected slots become `null` in a partial render.
- **Batch / All**: loops `renderCarousel(..., markSeen=true)` for dedup; "All" iterates every topic.

## For AI Agents

### Working In This Directory
- `StudioPage` is the single source of truth for workflow state — add new workflow state here and thread it to components via props.
- All backend interaction goes through `src/api.ts`; never `fetch` inline.
- Keep `ApiDocsPage`'s hardcoded `ENDPOINTS[]` and snippets **in sync with** `docs/API.md` and the actual `/api/v1` routes in `backend/api/v1.py`. Three places describe the same API — update them together.
- Renders are synchronous and slow (~10–30s); the page shows a loading state but has no cancel/timeout — don't assume instant responses.

### Testing Requirements
- No tests. Verify with `npm run lint`, `npm run build`, and manual browser walkthroughs of the full topic→export flow and each hotkey.

### Common Patterns
- Functional components, `useState`/`useEffect`, localStorage persistence, controlled children, Tailwind styling.

## Dependencies

### Internal
- `StudioPage` composes everything in `src/components/`; both pages use `src/types.ts` and (StudioPage) `src/api.ts`. `ApiDocsPage` mirrors `docs/API.md`.

### External
- react, react-router-dom (routing), Tailwind.

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->

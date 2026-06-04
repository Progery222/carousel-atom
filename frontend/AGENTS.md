<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-04 | Updated: 2026-06-04 -->

# frontend

## Purpose
The Carousel Studio UI: a single-page React 19 + Vite + Tailwind + TypeScript app on port 5173. It drives the studio workflow — pick topic → pick design → render → edit slides → export (ZIP / Telegram) — and also serves a static `/api-docs` page documenting the public API. All backend communication is funneled through one module (`src/api.ts`).

## Key Files
| File | Description |
|------|-------------|
| `package.json` | React 19, Vite, Tailwind, TypeScript, react-router-dom, jszip, file-saver. Scripts: `dev`, `build` (tsc + vite), `lint`, `preview`. No test runner. |
| `index.html` | Single entry; mounts `#root`, loads `/src/main.tsx`, imports the Inter font. |
| `vite.config.ts` | Minimal — `@vitejs/plugin-react` only. |
| `tailwind.config.js` | CSS-variable theme tokens (`--ink-900`…`--ink-100`, `--accent`); light/dark via `data-theme` on `<html>`. |
| `tsconfig*.json` | Project references (`tsconfig.app.json` for app, `tsconfig.node.json` for tooling); strict, no-emit. |
| `eslint.config.js` | Flat ESLint config with React Hooks, React Refresh, and TypeScript plugins. |
| `postcss.config.js` | Tailwind → Autoprefixer chain. |

## Subdirectories
| Directory | Purpose |
|-----------|---------|
| `src/` | Application source: pages, components, API client, types (see `src/AGENTS.md`) |
| `public/` | Static assets served as-is (`favicon.svg`, `icons.svg`) — no AGENTS.md |

## For AI Agents

### Working In This Directory
- `src/api.ts` is the **only** module that talks to the backend. New backend calls go there, not inline in components.
- The backend base URL comes from `VITE_CAROUSEL_API` (defaults to `http://localhost:8000` in dev; relative URLs in production where frontend + API share a host).
- State is React hooks + `localStorage` only — no Redux/Context. Persisted keys: `carousel-studio:runs:v1` (history), `carousel-studio:layout:v1`, `carousel-studio:theme:v1`. Don't rename these — it orphans user data.

### Testing Requirements
- **No test suite.** The only checks are `npm run lint` (eslint) and `npm run build` (tsc typecheck + vite build). Verify UI changes manually in the browser.

### Common Patterns
- Functional components, Tailwind utility classes, CSS-variable theming flipped by `<html data-theme>`.
- State is lifted to `StudioPage`; child components are controlled (state + callbacks flow down).
- Page-level hotkeys (G/E/B/A/V/P/Esc) are disabled inside text inputs.

## Dependencies

### Internal
- Routing in `src/App.tsx` → `src/pages/`; pages compose `src/components/`; all data via `src/api.ts`; shapes in `src/types.ts`.

### External
- react / react-dom 19, react-router-dom, tailwindcss, jszip + file-saver (ZIP export), vite + @vitejs/plugin-react, typescript, eslint.

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->

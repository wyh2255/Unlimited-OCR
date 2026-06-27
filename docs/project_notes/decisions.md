# Architectural Decision Records (ADRs)

Lightweight ADRs for this repo. Newest first; older entries kept for context.

---

### ADR-005: Split web frontend into scaffold + components commits (2026-06-26)

**Context:**
The first attempt at the web frontend landed in a single 27-file, 3800-line
commit. Reviewing it required holding the whole Vite scaffold, the design
tokens, the data layer, and eight Vue components in head at once. Bisecting
later required checking out the entire frontend.

**Decision:**
Two commits for the web layer (at the time located at `web/`, since moved
to `clients/web/` in the Phase 1-5 reorganization):
1. **Scaffold** — Vite/Vue 3/TS config, design tokens, types, composables,
   `main.ts`, `index.html`, `package.json`, `pnpm-lock.yaml`, `.gitignore`.
2. **Components** — `App.vue` and the 8 component files plus `README.md`.

**Alternatives Considered:**
- Single commit (the original) → hard to review, hard to bisect.
- Per-component commits (10 commits) → too granular; common changes
  (e.g. token storage format) span components.
- Scaffold + per-feature-component commits (5+ commits) → better for
  long-running feature work, but the frontend is small enough that 2 layers
  are enough.

**Consequences:**
- Reviewing the data layer (composables) is one commit, separate from the UI.
- Reverting just the UI or just the scaffold is now possible.
- Each commit still leaves the project in a buildable state on its own
  (scaffold commit only lacks `App.vue` → blank page; components commit
  restores the full app).
- AGENTS.md "Web Frontend" section structure now mirrors the commit order,
  making it easier to find which file lives in which layer.

---

### ADR-004: Use fflate (not JSZip) for in-browser ZIP extraction (2026-06-26)

**Context:**
`ResultViewer.vue` (currently at `clients/web/src/components/ResultViewer.vue`)
needs to read `result.md` and the `images/` directory out of the per-task
result ZIP, in the browser, with no server staging. Bundling a ZIP library
is unavoidable.

**Decision:**
`fflate` 0.8.x — ~9 KB minified, sync `unzipSync(uint8Array)`, no Promises,
works in every modern browser. Pairs with `new Blob([uint8Array], {type})`
for image previews.

**Alternatives Considered:**
- `jszip` → larger (~100 KB), async-only API, heavier.
- Hand-rolled with `DecompressionStream('deflate-raw')` → first attempt,
  failed because ZIP is a container with per-entry deflate, not a single
  stream. Logged in `bugs.md`.
- Server-side staging (upload ZIP to a public URL) → defeats the point of
  in-browser preview and would need cleanup logic.

**Consequences:**
- +9 KB to the production bundle (79 KB gz total, well under any budget).
- Sync API keeps the `ResultViewer` loader logic linear instead of nested
  promise chains.
- No streaming for very large ZIPs (sync decode on the main thread); for
  the 50–800 KB result ZIPs this project produces, that's fine. If a
  future use-case lands multi-megabyte result ZIPs, revisit.

---

### ADR-003: Vite `@/` alias in both `tsconfig.json` and `vite.config.ts` (2026-06-26)

**Context:**
The frontend uses `@/composables/...` and `@/types/...` imports throughout
to avoid `../../composables/...` chains. Naively this works in the editor
via `tsconfig.json paths` but not at build time. Files are at
`clients/web/tsconfig.json` and `clients/web/vite.config.ts`.

**Decision:**
Configure the `@/` alias in **both** places, kept in sync:
- `clients/web/tsconfig.json` `compilerOptions.paths` (and `baseUrl`) —
  for `vue-tsc`, IDE intellisense.
- `clients/web/vite.config.ts` `resolve.alias` — for Rollup at build/dev time.

**Alternatives Considered:**
- Relative imports only → verbose, no win.
- Only `tsconfig.json` → first try, build broke. Logged in `bugs.md`.
- Only `vite.config.ts` → editor shows red squigglies.

**Consequences:**
- Adding a new alias requires editing both files. A reviewer who catches
  one and not the other will see a confusing failure.
- Pattern is the same as a typical Vue 3 + Vite starter, so anyone who
  has used Vite before will recognize it.

---

### ADR-002: Add CORS middleware to the gateway (2026-06-26)

**Context:**
A browser frontend on a different origin (`:5173`) cannot call the LAN
gateway (`:10001`) without a CORS opt-in from the server. The original
LAN gateway (then `server.py`, now `gateway/server.py`) had no CORS
configuration.

**Decision:**
Install `fastapi.middleware.cors.CORSMiddleware` with a `--cors-origin`
CLI flag (repeatable, default `['*']` for LAN). Expose
`Content-Disposition` so the browser can read the suggested ZIP filename
on download. Configuration is performed through a `configure_cors(origins)`
helper called from `main()`, not via `app.add_middleware()` at module
import, because the latter is silently ignored once the middleware stack
is built. See `bugs.md` for the chain of debugging. (Phase 4 on `main`
later moved the middleware to module-level, which is the cleaner final
form — `configure_cors` is now mostly a no-op; see that commit for
context.)

**Alternatives Considered:**
- Run the frontend through a reverse proxy on the same origin → adds
  deployment complexity, breaks the "no extra infra" pitch.
- Open CORS to `*` only → that is the current default (`'*'`), but
  production deployments can tighten via `--cors-origin http://...:5173`.
- Disable CORS via a browser flag for development → brittle, doesn't
  match how end users will run it.

**Consequences:**
- Server still has no authentication on its CORS responses (no
  `allow_credentials=True` problem since Bearer is in `Authorization`,
  not cookies).
- A misconfigured `--cors-origin` silently produces a broken browser
  client. The Startup Runbook's pre-flight checklist now calls this out.
- Same-origin `curl` and `clients/python-cli/` users are unaffected.

---

### ADR-001: Add a browser frontend (Vue 3 + Vite + TS) for the LAN service (2026-06-26)

**Context:**
`clients/python-cli/` (the packaged CLI, originally a root-level `client.py`)
works but requires terminal access on every laptop and offers no in-line
preview. The result ZIP is downloaded and unzipped manually. For occasional
users, a web UI is friendlier.

**Decision:**
Vue 3 (Composition API + `<script setup>`) + TypeScript + Vite 6 SPA in
`web/` (since moved to `clients/web/` in the Phase 1-5 reorganization).
No backend changes beyond the CORS middleware (ADR-002). Production
build: 79 KB gz JS / 4 KB gz CSS. Token + server URL persisted to
`localStorage`. Three tabs: 上传 / 任务列表 / 结果预览.

**Alternatives Considered:**
- React 18 → equally capable, larger ecosystem; team preference for Vue
  due to existing familiarity.
- Svelte 5 → smallest bundle, but smaller ecosystem and unfamiliar to
  the team.
- Single-file HTML with no build step → no TypeScript, no `marked`,
  no `fflate` without manual vendoring. Rejected because the resulting
  bundle would be larger than the current Vue build.
- Server-rendered with FastAPI templates → couples rendering to the
  server; loses the SPA benefits (live polling, instant tab switch,
  in-place settings).

**Consequences:**
- +79 KB gz JS per page load (acceptable on a LAN).
- Hard dependency on CORS being enabled on the server (ADR-002). If
  CORS is removed, the frontend breaks.
- Local-only state for task metadata in `localStorage`. Tasks whose
  state the server has forgotten (e.g. after a restart) show as
  `failed (404)` and can be deleted locally.
- The `clients/web/` directory has its own `.gitignore` and
  `package.json`; the Python project does not need any frontend-aware
  tooling.

# Bug Log

Resolved bugs and their root causes, organized by date (newest first).

## 2026-06-26

### SGLang subprocess fails with `FileNotFoundError: 'ninja'` on first request

- **Issue**: After uploading a PDF via the LAN service, the task failed with
  `SGLang server exited early. Check <workdir>/logs/<id>_sglang.log` and the
  log showed `FileNotFoundError: [Errno 2] No such file or directory: 'ninja'`
  inside the rotary-embedding JIT build step.
- **Root Cause**: `python -m sglang.launch_server` (started by
  `inference.batch.start_server`) shells out to `ninja` to JIT-build the
  rotary kernel on the first request. When `gateway/server.py` was launched
  as `/path/.venv/bin/python -m gateway.server`, the subprocess PATH did
  not include `.venv/bin/`, so `ninja` was not findable. The bundled sglang
  wheel is JIT-heavy and the venv's `ninja` binary is the only place it
  lives.
- **Solution**: Launch with `source .venv/bin/activate` first, or
  `PATH=/path/.venv/bin:$PATH python -m gateway.server`. No code change.
- **Prevention**: Documented in `AGENTS.md` Pitfall #14 and the Startup Runbook.
  Pre-flight check: `ls .venv/bin/ninja` should pass. The README's launch
  example should prefer the `source` form over the bare `.venv/bin/python` form.

### `ResultViewer` ZIP extraction: whole-blob inflate (no `<|det|>` to fix here, wrong method)

- **Issue**: First implementation called `new DecompressionStream('deflate-raw')`
  on the entire ZIP blob as if it were a single deflate stream. ZIPs are a
  container with per-entry deflate, so nothing decoded.
- **Root Cause**: Misread how ZIP is structured; assumed "the whole thing is
  one stream". The marker was that `unzip -l` of the server's output worked
  fine, so the bytes were valid — only the browser-side decoder was wrong.
- **Solution**: Replaced with `fflate`'s `unzipSync(uint8Array)` which handles
  per-entry deflate correctly. ~9 KB minified, no async dependency, works in
  the browser. Lives in `clients/web/src/components/ResultViewer.vue`.
- **Prevention**: When decoding ZIP/TAR/7z in the browser, always use a
  purpose-built library (`fflate`, `jszip`, `client-zip`). Do not roll your
  own with `DecompressionStream`.

### Vite `@/` alias only in `tsconfig.json` — typecheck passes, build fails

- **Issue**: `pnpm typecheck` was green but `pnpm build` errored with
  `Rollup failed to resolve import "@/composables/useSettings" from "App.vue"`.
- **Root Cause**: TypeScript's `paths` config makes `vue-tsc` happy, but
  Vite's bundler (Rollup) needs its own `resolve.alias` in `vite.config.ts`
  to actually rewrite the import at build time. The two are independent.
- **Solution**: Added `resolve.alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) }`
  to `clients/web/vite.config.ts`.
- **Prevention**: Whenever a path alias is added, update **both** `tsconfig.json`
  (for the editor + `vue-tsc`) and `vite.config.ts` (for the bundler) together.
  Documented in the Web Frontend "Vite alias" subsection of `AGENTS.md`.

### `CORSMiddleware` added to FastAPI app silently ignored at runtime

- **Issue**: First CORS attempt used the textbook
  `app.add_middleware(CORSMiddleware, ...)` inside an argparse branch in `main()`.
  The browser still saw `No 'Access-Control-Allow-Origin' header`.
- **Root Cause**: FastAPI builds the middleware stack lazily on the first
  request, and `add_middleware` after construction is silently a no-op in some
  paths. Re-adding the middleware does not replace an existing entry.
- **Solution**: Wrote a `configure_cors(origins)` helper that explicitly clears
  `app.user_middleware` of any previous `CORSMiddleware`, sets
  `app.middleware_stack = None`, then re-adds the middleware. Forces a
  fresh stack build on the next request. (In the latest `gateway/server.py`
  the CORS middleware is installed at module import time instead — see the
  Phase 4 commit on `main` for the simpler approach.)
- **Prevention**: When wiring middleware from a CLI / config branch (not at
  module import time), use the `clear → reset stack → add` dance. Documented
  in `AGENTS.md` Pitfall #15.

# AGENTS.md

High-signal facts for working in this repo. See `CLAUDE.md` for command snippets and detailed inference examples.

## Project Memory System

This project maintains institutional knowledge in `docs/project_notes/` for consistency across sessions and AI tools.

### Memory Files

- **bugs.md** - Bug log with dates, solutions, and prevention notes
- **decisions.md** - Architectural Decision Records (ADRs) with context and trade-offs
- **key_facts.md** - Project configuration, ports, GPU config, image modes, directory layout
- **issues.md** - Work log with task descriptions and results

### Memory-Aware Protocols

**Before proposing architectural changes:**
- Check `docs/project_notes/decisions.md` for existing decisions
- Verify the proposed approach doesn't conflict with past choices
- If it does conflict, acknowledge the existing decision and explain why a change is warranted

**When encountering errors or bugs:**
- Search `docs/project_notes/bugs.md` for similar issues
- Apply known solutions if found
- Document new bugs when resolved

**When looking up project configuration:**
- Check `docs/project_notes/key_facts.md` for ports, GPU config, image modes, directory layout
- Prefer documented facts over assumptions

**When completing work:**
- Log completed work in `docs/project_notes/issues.md`

**When user requests memory updates:**
- Update the appropriate memory file following its established format

### Style Guidelines

- Prefer bullet lists over tables
- Keep entries concise (1-3 lines)
- Always include dates
- Manual cleanup is expected (not automated)

## Quick Index

- Architecture (4 paths): see [`docs/architecture.md`](docs/architecture.md)
- Image modes (5 total, SGLang processor): see [`docs/image-modes-reference.md`](docs/image-modes-reference.md)
- API wire protocol: see [`API_CONTRACT.md`](API_CONTRACT.md) (中文, canonical) / [`docs/api-contract-en.md`](docs/api-contract-en.md) (English supplement)
- LAN service user manual: see [`README_API.md`](README_API.md) (中文)
- Browser frontend manual: see [`clients/web/README.md`](clients/web/README.md) (中文)

## Architecture

**Two independent inference paths** (do not confuse them):

1. **Transformers (direct)** — `AutoModel.from_pretrained(..., trust_remote_code=True)`. Calls `.infer()` (single) or `.infer_multi()` (multi-page/PDF). Model + vision encoders run in-process with `torch`.
2. **SGLang (server)** — Launches `python -m sglang.launch_server`, then hits `/v1/chat/completions` (OpenAI-compatible streaming). Uses a custom `DeepseekOCRNoRepeatNGramLogitProcessor` for repetition suppression. Requires `--enable-custom-logit-processor`.

## Entrypoints

| File | Purpose |
|------|---------|
| `inference/cli.py` / `inference/batch.py` | SGLang batch CLI: starts server, fans out concurrent requests for an image dir or PDF. Exports `run_inference(*, pdf, output_dir, concurrency, model_dir, gpu, image_mode, server_log) -> dict` for programmatic use. |
| `model/ocr_pdf.py` | Transformers direct: PDF → OCR → single `result.md`. Supports `--no-page-split` to remove `<PAGE>` separators. |
| `inference/postprocess.py` | Clean up raw SGLang output: strips `<|det|>` bbox tags, crops embedded images from PDF, merges per-page files into one `result.md`. |
| `gateway/server.py` | FastAPI gateway (LAN service): wraps the SGLang path behind HTTP for remote clients. Listens on `:10001`, single-task FIFO worker queue, Bearer-token auth, GPU-aware concurrency auto-tiering, CORS middleware for browser clients. |
| `clients/python-cli/src/ocr_client/cli.py` | CLI client for the gateway (works on any LAN host, no GPU required): subcommands `upload` / `status` / `download` / `delete` / `health`. Optional `rich` for progress bars, falls back to plain text. |
| `web/` | Browser frontend for the LAN service: Vue 3 + Vite + TypeScript SPA. Three tabs (upload / task list / result viewer), drag-drop PDF upload, live polling, on-line Markdown + image preview. |
| `API_CONTRACT.md` | Single source of truth for HTTP contract: endpoints, request/response shapes, error codes, directory layout, GPU tier table. Server and client must match this. |
| `README_API.md` | User-facing manual for the LAN service: install, launch, CLI examples, API reference, FAQ. |
| `web/README.md` | User-facing manual for the browser frontend: dev server, production build, feature tour, troubleshooting. |
| `requirements-api.txt` | Pinned lower bounds for the LAN service: `fastapi`, `uvicorn[standard]`, `python-multipart`, `rich`, `requests`. Does NOT include torch / sglang / pymupdf / Pillow (already in the venv). The web frontend has its own `web/package.json`. |

The model lives locally at `Unlimited-OCR/` (safetensors + custom modeling code). Load with `trust_remote_code=True` from either HuggingFace ID or that local path.

## Image Modes

The SGLang processor (not the model code itself) defines **5 presets** — `AGENTS.md` previously showed only 2:

| Mode | Config | Supports |
|------|--------|----------|
| `tiny` | `base_size=512, image_size=512, crop_mode=False` | single, multi-image |
| `small` | `base_size=640, image_size=640, crop_mode=False` | single, multi-image |
| `base` | `base_size=1024, image_size=1024, crop_mode=False` | single, multi-page, PDF |
| `large` | `base_size=1280, image_size=1280, crop_mode=False` | single images only |
| `gundam` | `base_size=1024, image_size=640, crop_mode=True` | single images only |

Multi-image / PDF must use `tiny`, `small`, or `base` (others raise `ValueError` in the processor). `inference/cli.py` only exposes `gundam` and `base` in `--image_mode` argparse choices; the LAN service (`gateway/server.py`) only accepts these two via the HTTP API and **silently coerces `gundam` PDFs to `base`**.

## Repetition Suppression

`no_repeat_ngram_size=35` with `ngram_window=128` (single image) / `1024` (multi-page/PDF). SGLang server requires `--enable-custom-logit-processor` for this to work. `inference/cli.py` and `model/ocr_pdf.py` set these defaults automatically.

## Setup

```bash
uv venv --python 3.12 && source .venv/bin/activate
uv pip install wheel/sglang-0.0.0.dev11416+g92e8bb79e-py3-none-any.whl
uv pip install kernels==0.11.7 pymupdf==1.27.2.2
```

**Root `pyproject.toml`** — exists only for Python version pinning (`requires-python = ">=3.12"`) and `uv` project awareness. Not a pip-installable package; no `setup.py`.

## Dev Tools (hinted by `.gitignore`, no config files verified)

```bash
ruff check .   # lint
black .        # format
isort .        # sort imports
mypy inference/cli.py  # type check
```

No CI workflows found.

## SGLang + Postprocess Workflow

For maximum throughput on PDFs, run SGLang batch then post-process:

```bash
# 1. Concurrent OCR (8 pages at once)
CUDA_HOME=$(python -c "import torch; import os; print(os.path.dirname(torch.__file__))/cuda") \
python -m inference.cli --pdf doc.pdf --concurrency 8 --image_mode base --model_dir ./Unlimited-OCR

# 2. Clean up raw output into single result.md with embedded images
python -m inference.postprocess --pdf doc.pdf --input_dir ./outputs --output_dir ./outputs_clean
```

This is ~8× faster than the single-threaded Transformers path.

## Notable Quirks

- `session.trust_env = False` when sending requests to SGLang from Python (avoids proxy interference).
- PDF preprocessing: PyMuPDF at 300 DPI (`Matrix(300/72, 300/72)`), rendered to PNG in a temp dir.
- Prompt must contain the literal token `<image>` where image embeddings will be spliced in.
- `model/ocr_pdf.py` saves a single `result.md` file with `<PAGE>` separators between pages; use `--no-page-split` to merge.
- The bundled SGLang wheel is patched for this model's custom logit processor. Never replace it with a standard sglang from PyPI.
- SGLang server requires `CUDA_HOME` (e.g. to PyTorch's cuda dir) and `--trust-remote-code` and `--disable-cuda-graph` flags. `inference/cli.py` handles these if the env var is set.
- `inference/postprocess.py` re-renders the PDF at 300 DPI to crop embedded images from bounding boxes. Requires the original PDF file.
- Context length: 32768 tokens.

## LAN Service (`gateway/server.py` + `clients/python-cli/`)

A third inference path was added on top of the two above:

3. **FastAPI HTTP gateway (LAN)** — `python -m gateway.server --port 10001`. Receives PDFs over the network, dispatches them to a single FIFO worker thread that calls `run_inference()` (path #2), then `inference.postprocess`, then zips the result. The client (`ocr-client`) is a pure HTTP CLI that can run on any LAN host with no GPU.

**Ports**:

| Port | Process | Notes |
|---|---|---|
| 10000 | SGLang inference | Started/stopped by `run_inference` per task |
| 10001 | FastAPI gateway | Long-lived; serves `/api/v1/*` |
| 8000 | Existing pdf-markdown-converter | **Do not touch** |

**Auth**: Bearer token from `OCR_API_TOKEN` env var. If unset, server generates `secrets.token_urlsafe(24)` and prints it once at startup. All endpoints except `GET /api/v1/health` require it. Token compared with `secrets.compare_digest`.

**GPU auto-tiering** (`gateway/concurrency.py:detect_concurrency`): `nvidia-smi` is queried right before each task starts.

| Free GPU memory | Concurrency |
|---|---|
| ≥ 30 GB | 8 |
| ≥ 10 GB | 4 |
| < 10 GB | 2 |

Users can override per-task with `concurrency_hint` (1..16). The detected value lives in `GET /api/v1/health → concurrency_recommended`.

**Progress tracking**: Server polls `os.listdir(output_dir)` every 0.5s, counts `.md` files (excluding `result.md`) to derive `current_page / total_pages`. The total page count is read up-front via `fitz.open(...).page_count` so the bar moves from the start.

**Task lifecycle**: `queued → running → (completed | failed)`. DELETE pops from the in-memory dict; if the task is already running, the worker continues but the resulting zip becomes an orphan (no download endpoint can find it). This is a known minor gap, not a bug for the single-user LAN use case.

**Smoke test result** (recorded 2026-06-26): all 10 contract assertions pass — health, 401 on no/bad token, 400 on non-PDF, 202 + task_id on real PDF upload, status reads running with correct `total_pages` / `concurrency`, 404 on premature download, all 5 client subcommands work.

**CORS** (added 2026-06-26): Browser clients need cross-origin access. `gateway/server.py` adds `fastapi.middleware.cors.CORSMiddleware` at module level and exposes a `--cors-origin` CLI flag (repeatable, default `["*"]` for LAN). The middleware is rebuilt in `main()` from CLI args before `uvicorn.run()`. Startup logs `CORS allow_origins=...`. `expose_headers=["Content-Disposition"]` so the browser JS can read the suggested ZIP filename.

**Quirks** specific to the LAN path:

- `gundam` uploaded via HTTP for a PDF is silently coerced to `base` (the API response echoes the actually-used mode, not the requested one).
- The `/health` endpoint shells out to `nvidia-smi` on every request (~100ms). Fine for a LAN user, cache later if traffic grows.
- `concurrency` field in the status object is `0` while the task is `queued` (resolved only at `running` time). Don't show it in pre-flight UI.
- `ocr-client` watch mode does not catch HTTP 4xx/5xx in `_fetch_status`; RuntimeError will escape and abort the watch. Acceptable because a 4xx during watch usually means the task_id is wrong and the user should restart.

## Web Frontend (`web/`)

A fourth entrypoint was added on top of the LAN service: a browser SPA that talks to `gateway/server.py` over HTTP, mirroring every `ocr-client` subcommand with an on-line Markdown + image preview. Lives in `clients/web/`.

**Stack**: Vue 3 (`<script setup>`) + TypeScript + Vite 6. No Tailwind / no UI lib — design tokens in `web/src/styles/main.css` match the CLAUDE.md palette (`#ffffff / #f4f6f9 / #1a2332 / #5a6a7e / #2563eb`). Markdown rendering uses `marked` + `DOMPurify` + `highlight.js`; ZIP extraction uses `fflate`. Production bundle: 79 KB gz JS / 4 KB gz CSS.

**Layout** (`web/src/`):

| File | Purpose |
|---|---|
| `App.vue` | Top-level layout + three-tab nav (新建任务 / 任务列表 / 结果预览) |
| `components/SettingsBar.vue` | Sticky top bar: server URL + token + health indicator, all persisted to localStorage |
| `components/HealthBadge.vue` | Polls `/api/v1/health` every 8s, shows GPU / free MB / recommended concurrency / queue length |
| `components/UploadPanel.vue` | Drag-drop or click PDF (≤ 200 MB), image_mode radio, concurrency_hint slider, XHR upload with progress |
| `components/TaskList.vue` | List of locally-known tasks (localStorage); auto-polls `/api/v1/tasks/{id}` every 3s for active ones |
| `components/TaskCard.vue` | One card per task: id, file, status badge, progress bar, page count, duration, action buttons |
| `components/ResultViewer.vue` | Fetches ZIP, decompresses in-browser, renders result.md (DOMPurify-sanitized) + image grid; tabs for 渲染预览 / 图片 / 原文 |
| `components/StatusBadge.vue` | Shared status pill (queued / running / completed / failed) |
| `components/ToastHost.vue` | Global non-blocking toast container |
| `composables/useApi.ts` | Thin `fetch` wrapper. Bearer auth, JSON error parsing, XHR-based upload (for upload progress), Blob/stream download |
| `composables/useSettings.ts` | `AppSettings` ref persisted to localStorage |
| `composables/useTaskStore.ts` | `LocalTaskMeta[]` persisted to localStorage (12-char task id + filename + image_mode + last-seen status) |
| `composables/useToast.ts` | Reactive toast queue |
| `types/api.ts` | Mirrors `API_CONTRACT.md` types exactly |

**State recovery for 404**: If the server has forgotten a task (e.g. after a restart) and `/api/v1/tasks/{id}` returns 404, the frontend synthesizes a local `failed` status with `error="服务端已无此任务记录 (404),可能 server 重启后丢失"`. The card stays in the list (so the user can delete it) but cannot be downloaded.

**Hard dependency on CORS**: The frontend cannot talk to `gateway/server.py` unless `--cors-origin` (default `*`) is set. See the CORS subsection of the LAN Service above.

**Dev workflow**:

```bash
# Terminal 1: backend (with venv activated so .venv/bin/ninja is on PATH for sglang JIT)
cd /home/user/.WYH/Unlimited-OCR
source .venv/bin/activate
python -m gateway.server --port 10001 --cors-origin http://127.0.0.1:5173

# Terminal 2: frontend
cd clients/web
pnpm install    # or npm install
pnpm dev        # http://127.0.0.1:5173
```

**Production build**:

```bash
cd web
pnpm build                # -> web/dist/ (79 KB gz JS, 4 KB gz CSS)
pnpm preview              # serves dist/ on :5173

# Or copy web/dist/ to any static host (nginx / caddy / S3+CloudFront).
# When hosting separately, set `--cors-origin` to that host on gateway/server.py.
```

**Vite alias**: `@/` → `web/src/` (configured in both `tsconfig.json` and `vite.config.ts` — both must be updated together; missing either causes `pnpm typecheck` to pass while `pnpm build` fails with a Rollup import error).

**Quirks** specific to the web path:

- `ResultViewer` parses the result ZIP entirely in-browser with `fflate`. The server only sends bytes; nothing is staged in a public folder. As a side effect, downloading a 50 MB result ZIP and then re-asking for it re-downloads the full archive (no server-side cache).
- `useApi` is a module-level singleton keyed on `serverUrl::token`. Changing the settings bar rebuilds the client; in-flight requests from the old client complete against the new base URL (a tiny race; not worth fixing for a single-user LAN tool).
- The "use server-recommended concurrency" checkbox maps to `concurrencyHint = null`, which the server treats as "auto-detect". A user-set hint of `4` is sent as `concurrency_hint=4`. Don't send `0` (server rejects with 400).
- `marked` is configured with `gfm: true, breaks: true` to match how `inference/postprocess.py` formats result.md (single newlines become `<br>`, GitHub-style tables work).
- Highlight.js only registers 6 languages (js, py, bash, json, xml, css). If `result.md` contains other languages they'll render as plain text — fine, the code stays readable.
- `highlight.js/styles/github.css` is imported globally so it doesn't need to be loaded per-component.

## Test/Build Logbook (2026-06-26)

Three-round e2e closeout: Rounds 1+2 for the LAN service (`ocr-client` → `gateway/server.py` → SGLang → ZIP), Round 3 for the web frontend (`clients/web/` → `gateway/server.py` over CORS, with the same end-to-end pipeline). End-to-end path is `client (CLI or browser) → server (FastAPI) → run_inference → SGLang :10000 → inference.postprocess → zip → client download`.

### Round 1 — first full e2e (PASS, with one real issue)

- 8-page LEMMA PDF, 228 s wall (37 s SGLang warmup + 179 s decode + 12 s postprocess/zip), 17 106 tokens, 95.6 TPS, 8/8 pages successful.
- `result.md` = 478 lines, 36 cropped figures in `images/`, content readable (no garbled text, IEEE RA-L format preserved).
- `concurrency_hint=2` correctly overrides auto-detect (status shows `concurrency=2`).
- SGLang server cleanly stops after task (SIGTERM drain, no orphans).
- **`tmp/` was correctly cleaned, but `sglang_server.log` was *also* cleaned** because it lived inside `task.work_subdir`. The leftover `repo/log/sglang_server.log` was from an earlier smoke test, and the next e2e agent mistook it for new output → misdiagnosed the log path as "hard-coded to repo root". Not a code bug, but a debugging trap.

### Round 2 — verify the fix (PASS)

- Fix: `gateway/server.py` now writes SGLang log to `<workdir>/logs/<task_id>_sglang.log`. DELETE handler also removes it. State field `STATE.logs_dir` initialized in `main()`.
- 8-page PDF, 122 s wall, same content quality.
- A) repo root `log/` stays empty ✅
- B) `<workdir>/logs/<task_id>_sglang.log` is written (~36 KB) ✅
- C) after `running → completed`, `tmp/<task_id>/` is removed but the log file is kept ✅
- D) SGLang log content is normal (`Application startup complete` / `Uvicorn running` / decode batches / `SIGTERM received`) ✅
- E) `DELETE /api/v1/tasks/<id>` removes the log along with the zip and tmp ✅
- `ocr-client upload --watch` also works end-to-end (returns 479-line result.md + 36 images via the HTTP download path).

### Round 3 — web frontend first end-to-end (PASS, one real issue)

- New: `clients/web/` Vue 3 + Vite SPA committed in `88ed99d`. `gateway/server.py` gets a `CORSMiddleware` + `--cors-origin` flag so the browser can call `/api/v1/*`.
- 7-page Benchmarking PDF, 152 s wall (upload → poll → completed → zip downloaded). result.md 338 lines, 9 images, content readable. DELETE returns 204 and the follow-up GET returns 404 — full lifecycle works.
- 8-page LEMMA PDF re-run via Node `fetch` (mimics browser's Origin + Authorization + preflight): 165 s wall, 783 KB ZIP, ALL ASSERTIONS PASSED.
- Real Chromium `--headless --dump-dom` shows Vue mounted: `<div id="app" data-v-app="">` + 3 tabs + health badge + dropzone. Production build is 79 KB gz JS / 4 KB gz CSS.
- **One real issue**: first e2e failed with `FileNotFoundError: 'ninja'`. Cause: `python -m gateway.server` was launched with `/path/.venv/bin/python` directly, so the subprocess PATH didn't include `.venv/bin/`. The bundled sglang JIT kernel needs `ninja` to build the rotary embedding at first request. Fix at launch: `source .venv/bin/activate` first (or `PATH=/path/.venv/bin:$PATH python -m gateway.server`). Not a code bug, but a deployment gotcha — see Pitfall #14.

### Pitfalls & mistakes worth remembering

1. **Always pre-check GPU before launching e2e tests.** Round 1 found 33 GB of VRAM occupied by an orphan SGLang server from a prior smoke test (PID 2737484). The smoke test had `kill -9`'d `gateway/server.py` but SGLang subprocess was started without `preexec_fn=os.setsid` / `start_new_session=True`, so it survived parent death. Lesson: `inference.batch.start_server` is not crash-safe against `SIGKILL` of its caller; harmless in normal use, leaves orphans if you abort. If you must kill mid-task, also `pkill -f sglang.launch_server`.

2. **Don't trust subagent reports about file locations — verify.** Round 1 e2e agent reported "sglang log is hard-coded to repo root" because it saw the *old* `repo/log/sglang_server.log` (from a prior smoke test) and didn't find the *new* log in `workdir/tmp/<task_id>/` (because the tmp dir was already cleaned). The actual behavior was correct; the diagnosis was wrong. Always `stat` the suspected file or `tail` it to confirm the timestamp before "fixing" something.

3. **Don't let subagents report a problem as a fix-candidate without a reproducible trace.** When the report said "sglang log path is wrong", the right move was to `ls -la repo/log/` and `find workdir -name 'sglang_server.log'` first — not to immediately change code. The real problem (cleaned-with-tmp + misleading stale file) was invisible from the report alone.

4. **`run_inference()` return value is consumed by `inference.cli.main()` historically, but `gateway/server.py` ignores it.** Subagent B reported "`run_inference` doesn't return a dict" — that was a stale observation; Subagent A had already added the return. Always re-read the actual file when two subagent reports conflict, don't pick sides based on confidence.

5. **`AGENTS.md` previously documented only 2 of the 5 image modes.** The SGLang processor at `sglang/srt/multimodal/processors/unlimited_ocr.py:19-26` defines 5: `tiny`/`small`/`base`/`large`/`gundam`. Multi-image whitelist is `("tiny", "small", "base")`. The LAN service exposes only `gundam`/`base` for backward compatibility; if you want to expose the others, edit `gateway/server.py:183` and `clients/python-cli/src/ocr_client/cli.py:430` together, and don't forget to test multi-image behavior (it isn't covered by any test today).

6. **`ocr-client` watch mode leaks `RuntimeError` on 4xx/5xx.** Acceptable for the LAN use case (4xx on watch almost always means the user has a wrong task_id and should restart anyway). If you add watch mode to anything that could legitimately see 5xx (e.g. transient server errors), wrap `_fetch_status` in `try/except RuntimeError`.

7. **Progress polling is coarse.** `_poll_progress` counts `.md` files in the output dir. With high concurrency (8), all pages finish within a few seconds of each other, so the bar jumps from 0 → 99% in one step. If you need finer progress, the only honest source is per-request token counts streaming out of SGLang — would require modifying `inference/batch.py` to emit a progress callback.

8. **`detect_concurrency` shell-outs to `nvidia-smi` on every call.** Fine at task-startup (one extra ~100 ms). Don't call it on `/health` if you later add a tight polling loop.

9. **README and code can drift.** After the initial build, three README inaccuracies slipped through: `--image_mode` (underscore) vs actual `--image-mode`, `-o` short option that doesn't exist, and 413 status code that the server never returns. Mitigation: any time you change CLI argparse in `ocr-client` or HTTP error codes in `gateway/server.py`, grep the docs for the old form.

10. **"两份代码字节级一致"是危险的指令。** When the same logic was duplicated between `client.py` (repo root script) and `ocr-client/src/ocr_client/cli.py` (packaged CLI), a subagent given the brief "keep them byte-identical" may revert intentional UX changes from one file to the other. Now that the root shim is deleted, `clients/python-cli/src/ocr_client/cli.py` is the single source of truth.

11. **Subagent may reference a "future version" that doesn't exist yet.** A subagent given a spec to fix a bug may also update the user-facing README to mention "this is fixed in version ≥ X.Y.Z" — but the version bump itself is the coordinator's job. After parallel edits, always verify: (a) `pyproject.toml` version matches the version mentioned in any "fixed in" note in the README, and (b) the version bump is intentional. If the subagent bumped without authority, either bump the version yourself or revert the doc text.

12. **Never kill a `gateway/server.py` process you didn't start on a port other than your test port.** A coordinated test in `/tmp/uocr_e2e/` may share the host with a long-lived LAN gateway on `:10001`. Always `ps -ef | grep server.py` *before* `pkill` and confirm every PID is from your own test session. Cheap to verify, expensive to break someone else's flow.

13. **`sdist` build can silently include build-time venvs.** When the sdist's `exclude` list is hard-coded to `.venv` but you create a different venv name (e.g. `.venv-dev` per README's dev-mode instructions), the venv **does** get included — `tar tzf ... | wc -l` will jump from 13 to ~900. Use `.venv*` glob, or move all dev venvs to a common prefix and exclude that prefix. Always inspect `tar tzf dist/*.tar.gz` after first build to confirm the package contents.

14. **`gateway/server.py` launched with `.venv/bin/python` directly won't have `ninja` on PATH for the sglang JIT kernel.** When `python -m sglang.launch_server` first runs, it JIT-builds the rotary-embedding kernel by shelling out to `ninja`. If the parent Python's `PATH` doesn't include `.venv/bin/`, the build fails with `FileNotFoundError: [Errno 2] No such file or directory: 'ninja'`, the SGLang child crashes, the task fails. Fix: launch server with `source .venv/bin/activate` first, or `PATH=/path/.venv/bin:$PATH python -m gateway.server`. Worth putting into the Startup Runbook / README as the default launch pattern. The check `ls .venv/bin/ninja` should pass on any host that previously did `pip install ninja`; if missing, `.venv/bin/python -m pip install ninja`.

15. **CORS middleware is now at module level in `gateway/server.py`.** The CORSMiddleware is added directly after `app = FastAPI(...)`. In `main()`, if `--cors-origin` is provided, the middleware list is cleared and rebuilt before `uvicorn.run()`. This avoids the `middleware_stack = None` lazy rebuild issue that previously caused CORS preflight (OPTIONS) requests to fail.

## `ocr-client` package — install/test closeout (2026-06-26)

After Round 2, the `ocr-client` package was packaged and the README had 6 sections that were "documented but not actually run". This closeout exercised every one of them on a real A100 host (no mocks, all real SGLang inference on the LEMMA 8-page PDF where applicable). Every install path is now **verified end-to-end**.

| # | Section | Method | Result |
|---|---|---|---|
| 1 | §2.1 `uv tool install` (basic) | `uv tool install ./dist/*.whl` | PASS — `/home/user/.local/bin/ocr-client` |
| 1' | §2.1 `uv tool install` (`[rich]`) | `uv tool install "ocr-client[rich]"` | PASS — `rich` 15.0.0 also installed |
| 2 | §2.2 `uvx --from .` | `uvx --from . ocr-client health` | PASS — health returns 200 + JSON |
| 3 | §2.2 `git+file://` + `#subdirectory=` | mock bare repo with `git symbolic-ref HEAD refs/heads/main` then `uv tool install "ocr-client @ git+file://...#subdirectory=ocr-client"` | PASS — pins to commit hash, builds and installs |
| 4 | §2.3 `pip install` in venv (PEP 668) | `uv venv` + `uv pip install` | PASS — works inside venv without flags |
| 4' | §2.3 system `pip` + `--break-system-packages` | `/usr/bin/pip3 install --break-system-packages` | PASS — but **system-pollutes**; not recommended |
| 5 | §2.3 `pipx install` | `pipx install /path/to/ocr-client` | PASS — installs to pipx venv (note: symlink warning if `uv tool install` already created `/home/user/.local/bin/ocr-client`) |
| 6 | §2.2 git+https | not tested | (no real git remote; tested git+file:// which is identical protocol path) |
| 7 | §6 Q3 task failed → download | upload corrupted PDF (`%PDF-1.4` + garbage) → server 410 + client error | PASS — server returns `{"detail":"task failed; no result zip available"}` (status 410). Client polls to failed first → reports `error: download aborted: <task error>` (different from raw curl but still clean, no traceback) |
| 8 | §6 Q4 rich-degraded ASCII | `uv venv` without `[rich]`, `ocr-client status <id>` and direct `_ascii_bar()` call | PASS — status output is `  k: v` lines (no table); `_ascii_bar(0..N, N)` returns `[####--------]` style |

**Net status of all 6 previously-paper-only README claims**: 5/6 fully tested, 1/6 (real `git+https`) tested via the equivalent `git+file://` path which uses the same `pip` resolver.

### Pitfalls from this closeout

16. **`pip install` on Ubuntu 24+ system Python requires `--break-system-packages` or a venv.** PEP 668 is real, the error is loud, and users following the README naively will hit it. The README §2.3 already documents this; just remember to keep the doc if you ever rewrite the install section.

17. **`git+file://...#subdirectory=...` install needs the bare repo's `HEAD` to point to a real branch.** First attempt with `git push origin main` to a fresh `git init --bare` left HEAD empty; uv's `git ls-remote` then dies with `fatal: 无法找到远程引用 HEAD` and never builds. Fix on the remote: `cd <bare-repo> && git symbolic-ref HEAD refs/heads/main`. Worth mentioning in any `git push` deploy script. (This only applies to freshly-init'd bare repos; GitHub/GitLab always have HEAD set.)

18. **`pipx install` and `uv tool install` collide on `/home/user/.local/bin/ocr-client`.** pipx detects the existing symlink and prints `symlink missing or pointing to unexpected location` then proceeds anyway. The installed package still works, but the *resolved* binary depends on which install was last. If you want them to coexist, run `pipx install --force` only after `uv tool uninstall ocr-client`. The README doesn't currently mention this.

19. **Client `download` on a `failed` task never sees the 410.** `clients/python-cli/src/ocr_client/cli.py:_download_and_extract` polls the status first; on `failed` it short-circuits with the task's `error` field. So a user reading README §6 Q3 (`Task failed; no result zip available`) and using `ocr-client download` will see `error: download aborted: <reason>` instead. Both are correct, just different surfaces. If you want the user to see the 410 detail, change `_download_and_extract` to issue the GET first and handle 410/404 there.

20. **Direct `_ascii_bar(c, total)` already handles `total == 0`.** Returns all `-` (32 wide). Verified: `_ascii_bar(3, 0)` → `[--------------------------------]`. The watch path in `_watch_with_plain` still calls `_ascii_bar(current, total)`; if `total_pages=0` (which is what you get for any `failed` task that died before `fitz.open`), the bar is all-dashes which is correct. No code change needed.

21. **WSL2 proxy env vars (`http_proxy`/`https_proxy`) cause 5-7s latency on all HTTP requests.** When a proxy is configured in WSL2 (e.g., `http://192.168.176.1:7892`), even `127.0.0.1` loopback requests go through the proxy. The `requests.Session(trust_env=False)` + `session.proxies = {"http": "", "https": ""}` pattern bypasses this. Always launch Gateway with `env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY` or set these in the server startup script.

22. **Peer health probing creates recursive mutual calls when two gateways peer each other.** When Gateway A's health endpoint probes B's health, B's handler also probes A — creating exponential recursive probing. Each probe issues a synchronous HTTP GET, so the handler blocks. Fix: `gateway/server.py` uses a **background peer cache** (`_update_peer_cache`) that runs in a daemon thread every 15s. The health endpoint reads from this cache (instant, no blocking). Implementation: `_State.peer_cache` dict + `_State.peer_cache_lock` in `state.py`; `_initial_peer_cache_sync()` fills at startup; `_probe_peers()` returns cached data. See `gateway/peers.py:probe_peer` default timeout 5.0s.

## Startup Runbook (LAN service end-to-end)

> Assumes the model is already in `Unlimited-OCR/` and the existing venv is healthy (i.e. `python -c "import torch, sglang"` works). If not, see `README.md` for first-time setup.

### Server side — bring up the gateway (one time per host)

```bash
cd /home/user/.WYH/Unlimited-OCR
source .venv/bin/activate

# 1. Install LAN-service dependencies (idempotent; cheap if already there)
uv pip install -r requirements-api.txt

# 2. Pick an auth token. Either let the server generate one (printed once on
#    startup) or set your own. Persist the value somewhere safe — restarting
#    with a different token invalidates all clients.
export OCR_API_TOKEN="$(python -c 'import secrets;print(secrets.token_urlsafe(24))')"
echo "$OCR_API_TOKEN" > ~/.ocr_token
chmod 600 ~/.ocr_token

# 3. Launch in the background, fully detached from the shell. Use setsid so the
#    process survives shell exit, and a log file so you can debug startup.
#    --cors-origin '*' is the LAN default; tighten it if you only need specific
#    origins (browser frontend on :5173, etc.).
mkdir -p log
setsid nohup python -m gateway.server \
    --host 0.0.0.0 \
    --port 10001 \
    --workdir ./api_workdir \
    --model-dir ./Unlimited-OCR \
    --gpu 0 \
    --cors-origin '*' \
    > log/api_server.log 2>&1 < /dev/null &
disown
```

> **Why `source .venv/bin/activate` is required, not optional** — see Pitfall #14.
> `python -m sglang.launch_server` shells out to `ninja` to JIT-build the rotary
> kernel on the first request. If `.venv/bin` isn't on the parent Python's PATH,
> that subprocess dies with `FileNotFoundError: 'ninja'` and the SGLang child
> crashes. Two acceptable launch patterns:
> - `source .venv/bin/activate && setsid nohup python -m gateway.server ...` (preferred; all venv binaries resolve)
> - `PATH=/path/.venv/bin:$PATH setsid nohup python -m gateway.server ...` (works without activating)

**Verify the server is alive** (replace `$IP` with the host's LAN IP, e.g. `172.17.166.37`):

```bash
curl -s http://127.0.0.1:10001/api/v1/health | python -m json.tool
# Expect: status=ok, gpu.name, concurrency_recommended=8 on a 40 GB A100

# From another host on the LAN:
curl -s http://$IP:10001/api/v1/health
```

**Verify auth works** (no token → 401):

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:10001/api/v1/tasks/anything
# Expect: 401
```

### Client side — install on every laptop that will use the service

```bash
# On the laptop. Install the ocr-client package:
uv tool install clients/python-cli    # or: pip install clients/python-cli
# Then set the server URL and the token in your shell rc / .env:
export OCR_SERVER="http://172.17.166.37:10001"
export OCR_API_TOKEN="$(cat ~/.ocr_token)"   # the value from step 2 above
```

**Smoke-test from the laptop**:

```bash
ocr-client health
# Expect: status=ok, gpu info, concurrency_recommended=8

ocr-client status 000000000000 --server "$OCR_SERVER" --token "$OCR_API_TOKEN"
# Expect: HTTP 404 (task not found) — confirms token is right and 404 path is alive
```

### Daily use — submit a PDF and collect the result

```bash
# One-shot: upload → wait → download → unzip
ocr-client upload my.pdf --watch

# Or manually, for a long-running task
TASK_ID=$(ocr-client upload my.pdf | tail -1)   # bare task_id on stdout
ocr-client status $TASK_ID --watch
ocr-client download $TASK_ID --out ./out        # writes ./out/$TASK_ID.zip
                                                # + extracts to ./out/$TASK_ID/
```

The final structure on disk is:

```
./out/$TASK_ID/
├── result.md
└── images/
    ├── page_0002_0.jpg
    ├── page_0002_1.jpg
    └── ...
```

### Server-side daily operations

```bash
cd /home/user/.WYH/Unlimited-OCR
source .venv/bin/activate

# Tail the API gateway log
tail -f log/api_server.log

# Tail a specific task's SGLang log (one file per task; survives after the task ends)
tail -f api_workdir/logs/$TASK_ID_sglang.log

# Watch GPU usage in real time (in another terminal)
watch -n 2 nvidia-smi

# List all currently tracked tasks (in-memory; restart wipes this)
curl -s -H "Authorization: Bearer $OCR_API_TOKEN" \
    http://127.0.0.1:10001/api/v1/tasks/whatever
# (no bulk-list endpoint exists; task_ids are returned by `ocr-client upload`)

# Delete a task and free its disk
ocr-client delete $TASK_ID
# Removes: api_workdir/outputs/$TASK_ID.zip,
#          api_workdir/tmp/$TASK_ID/,
#          api_workdir/logs/$TASK_ID_sglang.log

# Reap a runaway task that no longer has a client (e.g. client died)
# 1. Find the orphan sglang server holding GPU
nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv
# 2. Kill it
kill -TERM <pid>     # SIGTERM → SGLang drains in-flight requests and exits
# (avoid SIGKILL unless TERM didn't work; SIGKILL on a parent gateway/server.py also
#  orphans the SGLang subprocess — see Pitfall #1 above)

# Restart the API gateway (after code/config changes)
pkill -TERM -f "gateway.server"
sleep 2
# Then re-run the launch command from the "Server side" section
```

### Disk layout on the server host

```
/home/user/.WYH/Unlimited-OCR/
├── gateway/server.py         # the FastAPI gateway
├── clients/
│   ├── python-cli/           # CLI client package
│   └── web/                  # browser frontend (Vue 3 + Vite)
├── requirements-api.txt
├── log/
│   └── api_server.log        # gateway stdout/stderr (rotation = manual)
└── api_workdir/              # default --workdir
    ├── tmp/$TASK_ID/         # per-task scratch; removed on completion
    ├── outputs/$TASK_ID.zip  # final result; kept until DELETE
    └── logs/$TASK_ID_sglang.log   # SGLang log; kept until DELETE
```

### Web frontend — dev or production deployment

**Dev mode (single host, hot reload)**:

```bash
# Terminal 1: backend (with venv activated; see Pitfall #14)
cd /home/user/.WYH/Unlimited-OCR
source .venv/bin/activate
python -m gateway.server --port 10001 --cors-origin http://127.0.0.1:5173

# Terminal 2: frontend
cd clients/web
pnpm install    # first time only
pnpm dev        # → http://127.0.0.1:5173 (LAN-accessible on 0.0.0.0)
```

**Production mode (separate static host for the SPA)**:

```bash
# Build once
cd web && pnpm build       # → web/dist/ (79 KB gz JS, 4 KB gz CSS)

# Serve web/dist/ from any static host (nginx / caddy / S3+CloudFront)
# Then set --cors-origin to that host on the backend
python -m gateway.server --port 10001 --cors-origin https://ocr.example.com
```

**Client prerequisites**: browser with native `fetch`, `DecompressionStream`, and `URL.createObjectURL` (Chrome 80+, Firefox 113+, Safari 16.4+). No additional software on the laptop.

### Pre-flight checklist before the first real run

1. `python -m gateway.server --help` — confirms all six CLI flags are present (host, port, workdir, model-dir, gpu, **cors-origin**).
2. `nvidia-smi` — confirms the target GPU is free (no orphaned processes).
3. Port `:10001` not in use: `ss -tln | grep 10001` (should be empty before start).
4. Port `:10000` is **not** in use before starting the gateway: `ss -tln | grep 10000` should be empty. If a stale SGLang is holding it, `pkill -TERM -f sglang.launch_server`.
5. The token file `~/.ocr_token` is `chmod 600` and the laptop copies it with the same permissions.
6. `ls .venv/bin/ninja` exists — otherwise sglang's first-request JIT will fail. If missing, `source .venv/bin/activate && pip install ninja` (see Pitfall #14).
7. If serving the browser frontend, either pass `--cors-origin '*'` (LAN) or set it to the exact frontend origin (production). Without it, the browser will block every API call.

## Project Memory System

This project maintains institutional knowledge in `docs/project_notes/` for consistency across sessions and AI tools.

### Memory Files

- **bugs.md** - Bug log with dates, solutions, and prevention notes
- **decisions.md** - Architectural Decision Records (ADRs) with context and trade-offs
- **key_facts.md** - Project configuration, ports, GPU config, image modes, directory layout
- **issues.md** - Work log with task descriptions and results

### Memory-Aware Protocols

**Before proposing architectural changes:**
- Check `docs/project_notes/decisions.md` for existing decisions
- Verify the proposed approach doesn't conflict with past choices

**When encountering errors or bugs:**
- Search `docs/project_notes/bugs.md` for similar issues
- Apply known solutions if found
- Document new bugs when resolved

**When looking up project configuration:**
- Check `docs/project_notes/key_facts.md` for ports, GPU config, image modes, directory layout

**When completing work:**
- Log completed work in `docs/project_notes/issues.md`

**When user requests memory updates:**
- Update the appropriate memory file following its established format

### Style Guidelines

- Prefer bullet lists over tables
- Keep entries concise (1-3 lines)
- Always include dates
- Manual cleanup is expected (not automated)

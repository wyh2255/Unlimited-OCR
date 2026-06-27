# Project Key Facts

Configuration, ports, env vars, and other stable facts. Update when something
in the project changes; do not delete old facts unless they are wrong.

## Ports

- **10000** — SGLang inference server. Started/stopped per task by
  `inference.batch.start_server()`. **Do not** bind a long-lived process here.
- **10001** — FastAPI gateway (`gateway/server.py`). Long-lived; serves
  `/api/v1/*`. Default port. Override with `--port`.
- **5173** — Vite dev server / `vite preview` (frontend). Default. Override
  with `pnpm dev --port`.
- **8000** — Pre-existing `pdf-markdown-converter`. **Do not touch.**

## Authentication

- Env var: `OCR_API_TOKEN`. If unset at server start, the server generates
  `secrets.token_urlsafe(24)` and prints it once to stdout. Persist the
  printed value to `~/.ocr_token` (chmod 600) for reuse.
- Header: `Authorization: Bearer <token>`.
- Comparison: `secrets.compare_digest`. Constant-time.
- `GET /api/v1/health` is the only endpoint that does **not** require auth.

## CORS

- Added 2026-06-26. Default `'*'` (LAN-safe). Tighten per deployment via
  `--cors-origin <url>` (repeatable).
- Exposes `Content-Disposition` so the browser can read the suggested
  ZIP filename on download.
- Implemented via `configure_cors()` in `gateway/server.py` (or directly
  as module-level middleware after the Phase 4 reorg on `main`; see
  `bugs.md` for the chain of debugging that led to the helper).

## GPU Auto-Tiering (`detect_concurrency`)

Queried right before each task starts via `nvidia-smi`:

- Free ≥ 30 GB → concurrency 8
- Free ≥ 10 GB → concurrency 4
- Free < 10 GB → concurrency 2

User override per-task: `concurrency_hint` field in `POST /api/v1/tasks`,
value 1–16. The detected value for a running task lives at
`GET /api/v1/health → concurrency_recommended`.

## Disk Layout (default `--workdir ./api_workdir`)

```
./api_workdir/
├── tmp/<task_id>/         # per-task scratch; removed on completion
├── outputs/<task_id>.zip  # final result; kept until DELETE
└── logs/<task_id>_sglang.log   # SGLang log; kept until DELETE
```

`DELETE /api/v1/tasks/<id>` removes all three.

## Image Modes (5 in SGLang processor; 2 exposed via API)

| Mode | base_size | image_size | crop_mode | Multi-image / PDF |
|------|-----------|------------|-----------|-------------------|
| `tiny` | 512 | 512 | False | yes |
| `small` | 640 | 640 | False | yes |
| `base` | 1024 | 1024 | False | yes |
| `large` | 1280 | 1280 | False | no |
| `gundam` | 1024 | 640 | True | no |

The LAN service (HTTP API + `clients/python-cli/`) only exposes `gundam` and `base`.
A `gundam` PDF is silently coerced to `base` (the API response echoes
the actually-used mode).

## Web Frontend Stack

- **Vue 3.5** with `<script setup>` and Composition API.
- **TypeScript** strict, `vue-tsc --noEmit` for type checks.
- **Vite 6** for dev / build. `@/` → `clients/web/src/` alias.
- **marked 15** + **DOMPurify 3** + **highlight.js 11** for Markdown
  rendering with XSS sanitization and code highlighting.
- **fflate 0.8** for in-browser ZIP decompression.
- Bundle: 79 KB gz JS / 4 KB gz CSS.
- Node 18+ for `fetch`; Chrome 80+ / Firefox 113+ / Safari 16.4+ for
  `DecompressionStream` and `URL.createObjectURL`.

## Repetition Suppression

- `no_repeat_ngram_size=35`
- `ngram_window=128` (single image) / `1024` (multi-page / PDF)
- Requires `--enable-custom-logit-processor` on the SGLang server
  (set automatically by `infer.start_server`).
- The bundled sglang wheel (`wheel/sglang-0.0.0.dev*.whl`) is patched
  for this model's custom logit processor. Never replace with PyPI sglang.

## Dependency Surface (Python venv)

- `.venv/` is the only venv. Created with `uv venv --python 3.12`.
- `wheel/sglang-0.0.0.dev11416+g92e8bb79e-py3-none-any.whl` is the
  SGLang wheel. Install via `uv pip install <wheel-path>`.
- `kernels==0.11.7` and `pymupdf==1.27.2.2` are required.
- `ninja` is required at runtime (sglang JIT). The venv has it
  (`ls .venv/bin/ninja` should pass).
- LAN-service deps are pinned in `requirements-api.txt`.

## Vite Alias Foot-Gun

`@/` must be configured in **both** `clients/web/tsconfig.json` (under
`compilerOptions.paths`) **and** `clients/web/vite.config.ts` (under
`resolve.alias`). Updating one and not the other causes
`pnpm typecheck` to pass while `pnpm build` fails (or vice versa).
See `bugs.md`.

## Default Task Lifecycle

```
queued → running → (completed | failed)
```

- `concurrency` is `0` while `queued` (resolved when `running`).
- `total_pages` is set when `running` starts (from `fitz.open(...).page_count`).
- `current_page` ticks up as `.md` files appear in the sglang output
  directory (polled every 0.5s, server-side).
- `progress` = `current_page / total_pages` capped at 0.99 until the
  postprocess step, then 1.0 on `completed`.
- A `failed` task has no result ZIP; the download endpoint returns
  410 instead of 404 in that case.

## Branch / Repository Notes

- All web work lives on the `feature/web-frontend` branch (off main).
  Main only has README history.
- Root `pyproject.toml` — exists only for Python version pinning (`requires-python = ">=3.12"`) and `uv` project awareness. Not a pip-installable package; no `setup.py`.
  Dependencies are listed in README and `requirements-api.txt`.
- The `ocr-client/` subdirectory is a separate packaging project, not
  related to `clients/web/`. Gitignored at the repo root.

## Hardware (Reference Host)

- Tested on: NVIDIA A100-SXM4-40GB, 40 GB total VRAM.
- OS: Linux (Ubuntu 24+ on the smoke test host), Python 3.12.
- Default port test on host: 10001 (gateway), 5173 (vite).
- Wall time for a 7-page Benchmarking PDF at concurrency 4: ~150 s.
- Wall time for an 8-page LEMMA PDF at concurrency 4: ~165 s.

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

- Header: `Authorization: Bearer <token>`.
- `GET /api/v1/health` is the only endpoint that does **not** require auth.
- **Single-token mode** (backward compat): env var `OCR_API_TOKEN`. If unset
  at server start, generates `secrets.token_urlsafe(24)` and prints once.
  owner fixed to `"self"`.
- **Multi-token mode** (Phase B): `~/.ocr_tokens.json` (or `--tokens-file` /
  `$OCR_TOKENS_FILE`). Format: `{"tokens": [{"token": "t1", "owner": "alice"}, ...]}`.
  Hot-reloaded on mtime change. Falls back to single-token mode when file
  absent. File permission `chmod 600` recommended.
- Token lookup via `gateway/users.py:UserRegistry.lookup()` (replaces the old
  `secrets.compare_digest` against `STATE.token`). Returns owner string or
  None. `gateway/auth.py:get_token` returns the owner, not the raw token.
- `GET /api/v1/me` → `{"owner": "..."}`. `GET /api/v1/tasks?scope=mine|all`
  filters by owner.

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

## Document Conversion (Phase A)

- `GET /api/v1/tasks/{id}/download?format=md|docx|html|pdf|latex` (default `md`,
  backward compatible — no `?format=` returns the original ZIP).
- Implemented in `gateway/convert.py` via pandoc subprocess. 5 formats:
  - `md`: plain copy of source ZIP (no pandoc call)
  - `docx`: pandoc default
  - `html`: `--standalone` + embed resources (version-dependent flag, see below)
  - `pdf`: `--standalone --pdf-engine <engine>` (default weasyprint)
  - `latex`: `--standalone` (full `\documentclass` document)
- `--resource-path <tmp_dir>` so pandoc finds `images/*.jpg`.
- HTML embedding flag is version-dependent: `--embed-resources` for pandoc
  ≥2.19, `--self-contained` for older. Detected by `_pandoc_version()` with
  lru_cache. See `bugs.md` 2026-06-30.
- Conversion timeout: 180s. Errors raise `ConversionError` → HTTP 500.
- Converted outputs cached at `outputs/{id}.{ext}`; second request for same
  format is instant (cache hit ~0.01s). DELETE clears all caches.
- CLI flag `--pandoc-pdf-engine` (default `weasyprint`; alt `xelatex`,
  `pdflatex`, `wkhtmltopdf`).
- System deps: `pandoc`, `libpango-1.0-0`, `libpangoft2-1.0-0`,
  `fonts-noto-cjk` (for CJK PDF). Python dep: `weasyprint>=60`.
- Dev host: pandoc 2.12 from conda, symlinked to `.venv/bin/pandoc` so it's
  on PATH without shadowing the venv python.

## 启动命令速查

### 开机完整启动流程 (RTX 4090)

```bash
cd /root/Unlimited-OCR

# 1. 激活虚拟环境
source .venv/bin/activate

# 2. 设置关键环境变量
export CUDA_HOME=/usr/local/cuda
export SGL_KERNEL_ARCH=90          # RTX 4090 (sm89) 强制使用 sm90 kernel
export OCR_API_TOKEN="$(cat ~/.ocr_token 2>/dev/null || python -c 'import secrets;print(secrets.token_urlsafe(24))')"

# 3. 设置 token 持久化（首次启动）
echo "$OCR_API_TOKEN" > ~/.ocr_token && chmod 600 ~/.ocr_token

# 4. 创建日志和临时文件目录
mkdir -p log api_workdir

# 5. 后台启动网关服务
setsid nohup python -m gateway.server \
    --host 0.0.0.0 \
    --port 10001 \
    --workdir ./api_workdir \
    --model-dir ./Unlimited-OCR \
    --gpu 0 \
    --cors-origin '*' \
    > log/api_server.log 2>&1 < /dev/null &
disown

# 6. 验证
sleep 3
curl -s http://127.0.0.1:10001/api/v1/health | python -m json.tool
```

### 一键脚本 `/root/Unlimited-OCR/start_server.sh`

```bash
#!/bin/bash
set -e
cd "$(dirname "$0")"
source .venv/bin/activate
export CUDA_HOME=/usr/local/cuda
export SGL_KERNEL_ARCH=90
OCR_API_TOKEN="$(cat ~/.ocr_token 2>/dev/null || python -c 'import secrets;print(secrets.token_urlsafe(24))')"
echo "$OCR_API_TOKEN" > ~/.ocr_token && chmod 600 ~/.ocr_token
export OCR_API_TOKEN
mkdir -p log api_workdir
setsid nohup python -m gateway.server \
    --host 0.0.0.0 --port 10001 \
    --workdir ./api_workdir \
    --model-dir ./Unlimited-OCR \
    --gpu 0 --cors-origin '*' \
    > log/api_server.log 2>&1 < /dev/null &
disown
echo "Gateway server starting on port 10001 (PID $!)"
echo "Token: $OCR_API_TOKEN"
```

### 必须的环境变量

| 变量 | 值 | 原因 |
|------|----|------|
| `CUDA_HOME` | `/usr/local/cuda` | SGLang 需要找到 nvcc |
| `SGL_KERNEL_ARCH` | `90` | RTX 4090 (sm89) 只能用 sm90 kernel |
| `OCR_API_TOKEN` | 随机字符串 | API Bearer token |

### 缺失系统包

如果遇到 JIT 编译失败，检查以下系统包：

```bash
apt-get install -y libnuma-dev g++ ninja-build
```

### 验证清单

```bash
# GPU 可用
nvidia-smi

# Python 可用
source .venv/bin/activate && python -c "import torch,sglang,fitz; print('OK')"

# 端口空闲
ss -tln | grep -E '1000[01]' || echo "OK"

# ninja 可用
ls .venv/bin/ninja

# sgl_kernel 兼容
python -c "import os; os.environ['SGL_KERNEL_ARCH']='90'; from sgl_kernel import common_ops; print('sgl_kernel OK')"
```

另见 `bugs.md` 2026-06-26、2026-07-01（ninja）和 2026-07-26（sgl_kernel 架构 / g++）。

## Disk Layout (default `--workdir ./api_workdir`)

```
./api_workdir/
├── tmp/<task_id>/                        # per-task scratch; removed on completion
├── outputs/<task_id>.zip                 # final result (result.md + images/); kept until DELETE
├── outputs/<task_id>.{docx,html,pdf,tex} # conversion cache (Phase A); kept until DELETE
├── logs/<task_id>_sglang.log             # SGLang log; kept until DELETE
└── tasks.db                              # sqlite task persistence (Phase B)
```

`DELETE /api/v1/tasks/<id>` removes zip + all 4 format caches + tmp + log +
sqlite row.

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
- 安装分两步：
  1. `uv pip install wheel/sglang-0.0.0.dev11416+g92e8bb79e-py3-none-any.whl`
     — sglang 定制 wheel，内部声明了 torch、transformers、flashinfer、ninja
     等核心 ML 依赖的精确版本（见 wheel 的 `METADATA` Requires-Dist）
  2. `uv pip install -r requirements-api.txt`
     — 项目级依赖清单，分三层：
       - ML 层：pymupdf（sglang wheel 未覆盖的）
       - 服务层：fastapi、uvicorn、weasyprint 等
       - 开发层（注释掉）：ruff、black、isort、mypy
- `ninja` 由 sglang wheel 自动安装，位于 `.venv/bin/ninja`。
  启动 SGLang 前确保 PATH 包含 `.venv/bin/`（见上面"启动命令速查"）。
- LAN-service deps are pinned in `requirements-api.txt`（重构后的完整版）。

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
- No `pyproject.toml` / `setup.py` — not a pip-installable package.
  Dependencies are listed in README and `requirements-api.txt`.
- The `ocr-client/` subdirectory is a separate packaging project, not
  related to `clients/web/`. Gitignored at the repo root.

## Hardware (Reference Host)

- Tested on: NVIDIA A100-SXM4-40GB, 40 GB total VRAM.
- OS: Linux (Ubuntu 24+ on the smoke test host), Python 3.12.
- Default port test on host: 10001 (gateway), 5173 (vite).
- Wall time for a 7-page Benchmarking PDF at concurrency 4: ~150 s.
- Wall time for an 8-page LEMMA PDF at concurrency 4: ~165 s.

## Task Persistence (Phase B)

- `api_workdir/tasks.db` (stdlib sqlite3, no new dependency).
- TaskState saved on every status transition (queued/running/completed/failed).
- On restart: running tasks → completed (if zip exists) or failed
  (error="server restarted").
- DELETE removes the sqlite row along with zip/tmp/log/cache.

## Multi-User (Phase B)

- UserRegistry reads ~/.ocr_tokens.json (or --tokens-file / $OCR_TOKENS_FILE).
- Token → owner mapping. Hot-reload on mtime change.
- Single-token fallback: OCR_API_TOKEN env, owner="self".
- TaskState.owner field. _task_to_dict outputs it.
- GET /api/v1/me → {"owner": "..."}. GET /api/v1/tasks?scope=mine|all.
- 2-10 person trust model: all scope shows all tasks, no per-task ACL.

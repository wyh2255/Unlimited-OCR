---
日期: 2026-06-26
文档类型: 架构文档
文档概述: 介绍本仓库的 4 条推理路径及相互关系
---

# Architecture

This fork ships **four mutually independent inference paths** on top of the upstream Baidu `baidu/Unlimited-OCR` model. Each path targets a different deployment scenario. They share the same model weights and processor, but not the same code.

## The four paths

| # | Path | Mode | Use case | Entry |
|---|------|------|----------|-------|
| 1 | **Transformers (direct)** | Single-GPU, in-process | One-off PDF, simplest setup | `python -m model.ocr_pdf doc.pdf` |
| 2 | **SGLang batch** | Server + clients, single host | High-throughput batch processing | `python -m inference.cli --pdf doc.pdf --concurrency 8` |
| 3 | **LAN HTTP gateway** | Network service, multi-client | Share a GPU across the LAN | `python -m gateway.server --port 10001` |
| 4 | **Browser frontend** | Vue 3 SPA over the LAN API | Non-technical end users | `cd clients/web && pnpm dev` |

## Path 1: Transformers (direct)

- **What it does**: loads the model in-process with `AutoModel.from_pretrained(..., trust_remote_code=True)`, then calls `model.infer()` (single image) or `model.infer_multi()` (multi-page PDF).
- **Output**: a single `result.md` with `<PAGE>` separators between pages (use `--no-page-split` to remove).
- **Hard-coded config**: `image_size=1024` (the `base` mode), `no_repeat_ngram_size=35`, `ngram_window=1024` (multi-page).
- **File**: `model/ocr_pdf.py` (128 lines).
- **Quirk**: images are NOT cropped or embedded by `model/ocr_pdf.py` itself; the model's own `save_results=True` emits `images/page_{N}_0.jpg` for pages that contain figures.
- **GPU**: occupies the whole GPU until the process exits. No concurrent multi-user support.

## Path 2: SGLang batch

- **What it does**: starts a SGLang server on `:10000`, fans out concurrent OpenAI-compatible `/v1/chat/completions` requests via a `ThreadPoolExecutor`, then writes one `.md` per page (raw — still contains `<|det|>` bbox tags).
- **Output**: `<output_dir>/<pdf-stem>_page_NNNN.md` (per-page, raw) for PDFs, or `<output_dir>/<stem>.md` for image dirs.
- **Custom logit processor**: `DeepseekOCRNoRepeatNGramLogitProcessor` (in the bundled `wheel/sglang-0.0.0.dev11416+g92e8bb79e-py3-none-any.whl`).
- **Repetition suppression**: `no_repeat_ngram_size=35`, `ngram_window=128` (single image) / `1024` (multi-page/PDF).
- **File**: `inference/cli.py` (34 lines). Exposes `main()` (CLI); `inference/batch.py` exports `run_inference()` (programmatic, used by Path 3).
- **Server launch flags required**: `--attention-backend fa3 --page-size 1 --mem-fraction-static 0.8 --context-length 32768 --enable-custom-logit-processor --disable-overlap-schedule --skip-server-warmup --trust-remote-code --disable-cuda-graph --host 0.0.0.0 --port 10000`.
- **Speed**: ~8× faster than Path 1 for multi-page PDFs.

## Path 3: SGLang + postprocess

- **What it does**: Path 2 + a cleanup step (`inference/postprocess.py`) that strips `<|det|>` bbox tags, crops image regions from the corresponding PDF page render, replaces them with `![](images/...)`, and merges all pages into one `result.md` joined by `<PAGE>`.
- **Output**: `<output_dir>/result.md` + `<output_dir>/images/page_NNNN_K.jpg` (4-digit page index, per-image counter, JPEG quality 92).
- **File**: `inference/postprocess.py` (~177 lines).
- **PDF rendering**: re-runs PyMuPDF at 300 DPI to get the bbox crops. Requires the original PDF file (`--pdf`).

## Path 4: LAN HTTP gateway (FastAPI)

- **What it does**: HTTP server on `:10001` that accepts PDF uploads over the network, dispatches them to a single FIFO worker thread that runs Path 3 (SGLang + postprocess), then zips the result for download.
- **Auth**: Bearer token via `Authorization: <token>` header. Token from `OCR_API_TOKEN` env var or generated on startup via `secrets.token_urlsafe(24)`.
- **Endpoints**: 5 (`/health`, `POST /tasks`, `GET /tasks/{id}`, `GET /tasks/{id}/download`, `DELETE /tasks/{id}`) — see [`API_CONTRACT.md`](../API_CONTRACT.md) (中文) or [`api-contract-en.md`](api-contract-en.md) (English).
- **Progress**: per-task thread polls `os.listdir(output_dir)` every 0.5s, counts `.md` files.
- **GPU auto-tiering**: `detect_concurrency` shells out to `nvidia-smi`. Free ≥30 GB → 8 concurrent; ≥10 GB → 4; <10 GB → 2. User override via `concurrency_hint` (1..16).
- **Files**: `gateway/server.py` (197 lines) + `gateway/tasks.py` + `clients/python-cli/src/ocr_client/cli.py`.
- **Quirks**:
  - `gundam` uploaded via HTTP for a PDF is silently coerced to `base` (the API response echoes the actually-used mode).
  - `concurrency` field in status is `0` while the task is `queued`.
  - DELETE on a running task lets the worker continue; the resulting zip becomes an orphan (no download endpoint can find it).

## Path 5: Browser frontend (Vue 3 SPA)

- **What it does**: Vue 3 + Vite + TypeScript SPA that talks to Path 4 over HTTP. Three tabs (upload / task list / result viewer), drag-drop PDF upload, live polling, on-line Markdown + image preview.
- **Stack**: Vue 3 (`<script setup>`) + TypeScript + Vite 6. No Tailwind / no UI lib — design tokens in `web/src/styles/main.css` match the project's CLAUDE.md palette.
- **Markdown rendering**: `marked` + `DOMPurify` + `highlight.js`. ZIP extraction: `fflate`. Production bundle: 79 KB gz JS / 4 KB gz CSS.
- **Hard dependency on CORS**: the browser blocks every API call unless `gateway/server.py` is started with `--cors-origin '*'` (or the specific frontend origin).
- **State recovery for 404**: if the server has forgotten a task (e.g. after a restart), the frontend synthesizes a local `failed` status with a user-visible message. The card stays in the list (so the user can delete it) but cannot be downloaded.

## How paths relate

```
        ┌─────────────┐
        │  PDF / PNG  │
        └──────┬──────┘
               │
       ┌───────┴─────────────────────────┐
       │                                 │
       ▼                                 ▼
┌──────────────┐                ┌──────────────────┐
│ Transformers  │                │  SGLang (port    │
│   (direct)    │                │      10000)      │
        │  Path 1       │                │   Path 2         │
        │  model/       │                │  inference/cli.py│
        │  model/       │                │                  │
        │  ocr_pdf.py   │                │                  │
        └──────┬───────┘                └─────┬────────────┘
               │                               │
               │ result.md                     │ per-page .md (raw)
               │                               ▼
               │                       ┌──────────────────┐
               │                       │ postprocess      │
               │                       │ inference/       │
               │                       │ postprocess.py   │
               │                       │ Path 3           │
               │                       └─────┬────────────┘
       │                             │ result.md + images/
       │                             ▼
       │                     ┌──────────────────┐
       │                     │  LAN gateway     │
       │                     │  (port 10001)    │
       │                     │  Path 4          │
        │                     │  gateway/        │
        │                     │  server.py       │
       │                     └─────┬────────────┘
       │                           │ HTTP + Bearer
       │                           ▼
        │                    ┌─────────────────┐
        │                    │  CLI client     │ (Path 4a,  python-cli/)
       │                    │  ocr-client     │ (Path 4b,  pip package)
        │                    │  Web frontend   │ (Path 5,   clients/web/)
       │                    └─────────────────┘
       │
       └────── both end at: ./<workdir>/<task_id>/{result.md, images/}
```

## Choosing a path

- **Just want to OCR one PDF locally?** → Path 1 (`python -m model.ocr_pdf doc.pdf`).
- **Have a 50-page PDF and want it done in 2 minutes on one GPU?** → Path 2 (`python -m inference.cli --concurrency 8`) + `python -m inference.postprocess`.
- **Want to share a GPU across multiple laptops on the LAN?** → Path 3 (start `python -m gateway.server` once, then `ocr-client upload` from each laptop).
- **Want the same as Path 3 but with a UI?** → Path 4 (add `cd clients/web && pnpm dev` to Path 3's setup, open `http://<server-laptop>:5173`).
- **Want to install a single CLI on every laptop and have it talk to one server?** → `pip install -e ocr-client/` (or `uv tool install`).

## Not a path: the `ocr-client` pip package

`ocr-client/` is a packaging wrapper around the same logic as `clients/python-cli/src/ocr_client/cli.py`. It's a dist of Path 4a, not a separate inference path. See [`ocr-client/README.md`](../ocr-client/README.md) (中文) for install.

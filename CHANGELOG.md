---
日期: 2026-06-26
文档类型: 变更日志
文档概述: 记录相对上游 Baidu/DeepSeek-OCR 的本地新增内容
---

# Changelog

This fork is based on [baidu/Unlimited-OCR](https://huggingface.co/baidu/Unlimited-OCR) (MIT, paper arXiv:2606.23050). The first 5 commits are upstream (README, LICENSE, CONTRIBUTING, .gitignore, `infer.py`, `assets/`, `wheel/`, `Unlimited-OCR.pdf`).

The following 5 commits are local additions, all authored on 2026-06-26:

## Commits (oldest → newest)

| SHA | Subject | What it adds |
|---|---|---|
| `c79996f` | Add LAN service core | `gateway/server.py` (FastAPI gateway), `clients/python-cli/` (CLI), `model/ocr_pdf.py` (Transformers direct), `inference/postprocess.py`, `inference/cli.py` + `inference/batch.py` patches, `requirements-api.txt`, `AGENTS.md` (initial 467 lines), `CLAUDE.md`, `API_CONTRACT.md`, `README_API.md` |
| `ee7bdcb` | Add CORS middleware to `gateway/server.py` | `CORSMiddleware` import at module level, `--cors-origin` CLI flag, startup log line, `Content-Disposition` expose header — to allow the browser frontend to call the LAN gateway |
| `84a6c69` | Add web frontend scaffold | `web/` (Vite 6 + Vue 3 + TypeScript 5.7) — empty scaffold, `package.json`, `vite.config.ts`, `tsconfig.json`, design tokens, favicon |
| `7695f6f` | Add web frontend components and App shell | `web/src/` — 9 Vue components, 4 composables, 3 tabs (upload / tasks / result), 79 KB gz production bundle |
| `74670e8` | Add ocr-client package + AGENTS.md install/test closeout | `ocr-client/` as a pip-installable wrapper around `clients/python-cli/` (package name `ocr_client`, console script `ocr-client`); AGENTS.md install/test closeout for 6 README sections |

## Code paths introduced (none upstream)

| Path | File (current location) | Purpose |
|------|------------------------|---------|
| Transformers-direct | `model/ocr_pdf.py` | Single GPU, in-process, single `result.md` output |
| SGLang batch | `inference/cli.py` / `inference/batch.py` | Concurrent SGLang, per-page `.md` files (raw) |
| SGLang + postprocess | `inference/postprocess.py` | Cleans raw output, embeds cropped images, produces `result.md` + `images/` |
| LAN HTTP gateway | `gateway/server.py` | FastAPI, Bearer auth, FIFO worker queue, zip-on-completion |
| CLI client | `clients/python-cli/src/ocr_client/cli.py` | Mirrors HTTP API, rich/ASCII progress |
| Web frontend | `web/` | Vue 3 SPA over the LAN API |

## Upstream (unchanged since forking)

- `README.md` (English, marketing, model inference) — kept verbatim except for 4 small typo fixes
- `CONTRIBUTING.md` (English + 中文 PR guidelines) — kept verbatim; URL is the Baidu repo by upstream design
- `LICENSE` (MIT, Baidu 2026)
- `Unlimited-OCR/` (ModelScope snapshot, 6.3 GB safetensors)
- `wheel/sglang-0.0.0.dev11416+g92e8bb79e-py3-none-any.whl` (12 MB)
- `assets/`, `Unlimited-OCR.pdf`

## What this repo provides on top

1. A second, network-reachable inference path (the LAN gateway) so the model can serve multiple clients without each client needing a GPU.
2. A browser frontend so non-technical users can upload PDFs without a CLI.
3. A pip-installable `ocr-client` package so laptops without GPUs can talk to the gateway.
4. Operational documentation in `AGENTS.md` (English runbook + pitfall logbook) and Chinese user manuals in `README_API.md`, `API_CONTRACT.md`, `web/README.md`, `ocr-client/README.md`.

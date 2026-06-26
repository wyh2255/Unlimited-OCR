---
日期: 2026-06-26
文档类型: 参考文档
文档概述: SGLang 处理器定义的 5 种 image mode 权威参考
---

# Image Modes Reference

The SGLang processor (not the model code itself) defines **5 image-mode presets**. They live in `sglang/srt/multimodal/processors/unlimited_ocr.py` of the bundled `wheel/sglang-0.0.0.dev11416+g92e8bb79e-py3-none-any.whl`.

## The 5 presets

| Mode | `base_size` | `image_size` | `crop_mode` | Multi-image / PDF? | Typical use |
|------|-------------|--------------|-------------|--------------------|-------------|
| `tiny`   | 512  | 512  | `False` | ✓ | Quick OCR of small / low-res images |
| `small`  | 640  | 640  | `False` | ✓ | Compromise between speed and accuracy |
| `base`   | 1024 | 1024 | `False` | ✓ | **Default for PDFs and multi-image** |
| `large`  | 1280 | 1280 | `False` | ✗ | Single high-res images that need fine detail |
| `gundam` | 1024 | 640  | `True`  | ✗ | Single image, dynamic cropping — best for documents with mixed content density |

> ⚠️ **Multi-image / PDF paths only accept `tiny`, `small`, or `base`.** The other two raise `ValueError` in the processor at request time.

## Where each preset is exposed

| Surface | Modes accepted | Where |
|---------|----------------|-------|
| `infer.py` CLI (`--image_mode`) | `gundam`, `base` | `infer.py:324` (argparse `choices`) |
| `run_inference(image_mode=...)` | `gundam`, `base` | `infer.py:338` (validated by argparse) |
| `ocr_pdf.py` | hard-coded to `base` (image_size=1024) | `ocr_pdf.py:88` |
| LAN HTTP API (`image_mode` form field) | `gundam`, `base` | `server.py:201` |
| LAN HTTP API for PDFs | **always `base`** (silent coercion of `gundam` → `base`) | `server.py:223, 235, 363` |
| `client.py` CLI (`--image-mode`) | `gundam`, `base` | `client.py:429` (argparse) |
| Web frontend radio | `gundam`, `base` | `web/src/components/UploadPanel.vue`, `web/src/types/api.ts` |

> The other 3 modes (`tiny`, `small`, `large`) are **defined by the SGLang processor** but **not exposed by any of the user-facing surfaces**. To use them, call `run_inference(image_mode="tiny")` programmatically and add `("tiny", "small", "large")` to the validation whitelist in `server.py:183` and `client.py:430`. Multi-image behavior is not covered by any test today.

## How `crop_mode` works

- `crop_mode=False` (most presets): the image is resized to `image_size × image_size` and sent as one tile.
- `crop_mode=True` (only `gundam`): the image is dynamically tiled. `image_size=640` is the tile size; `base_size=1024` is the global-view size. Best when the image has both dense text and sparse large figures (e.g. academic papers, slide decks).

## Effect on token budget

Rough rule: a `1024×1024` base tile uses ~1.3 K vision tokens. A `640×640` gundam tile uses ~0.5 K. Multi-page documents with high `image_size` consume the context window faster (context length is 32 768 tokens).

## Why this doc exists

`AGENTS.md` previously documented only `gundam` and `base`. The other 3 modes (`tiny`, `small`, `large`) are part of the SGLang processor surface but were not surfaced anywhere except the processor source. This file is the **single source of truth** for all 5 modes; everywhere else links back to it.

If you add a 6th mode in the SGLang processor, update the table above + the multi-image whitelist + every CLI's `choices=` argument.

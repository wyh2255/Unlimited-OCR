# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Unlimited-OCR is a one-shot long-horizon OCR parsing model by Baidu Inc. that treats document parsing as a vision-language task — given an image prompt, it generates structured markdown output with text, layout, and table content in a single forward pass.

- Paper: https://arxiv.org/abs/2606.23050
- Model: https://huggingface.co/baidu/Unlimited-OCR

## Architecture & Inference Paths

The model itself is loaded from HuggingFace (`baidu/Unlimited-OCR`) as a transformer with `trust_remote_code=True`. There are two independent inference paths:

1. **Transformers (direct)** — Load model via `AutoModel.from_pretrained`, call `.infer()` (single image) or `.infer_multi()` (multiple images/PDF). Requires `torch` + `transformers`.

2. **SGLang (server)** — Launch an SGLang server via `python -m sglang.launch_server`, then stream requests through an OpenAI-compatible `/v1/chat/completions` endpoint. Uses a custom `DeepseekOCRNoRepeatNGramLogitProcessor` for repetition suppression.

### Image Modes

- **`gundam`**: `base_size=1024, image_size=640, crop_mode=True` — single images only
- **`base`**: `base_size=1024, image_size=1024, crop_mode=False` — single, multi-page, and PDF

PDF and multi-page parsing only support the `base` mode.

### Key Files

| File | Purpose |
|------|---------|
| `infer.py` | CLI entry point for concurrent batch inference via SGLang. Starts the server, fans out requests with `ThreadPoolExecutor`, collects streaming results. |
| `wheel/sglang-0.0.0.dev*.whl` | Bundled SGLang wheel (patched for Unlimited-OCR's custom logit processor) |
| `assets/` | Demo images and GIFs for README |

## Commands

### Environment Setup

```bash
uv venv --python 3.12
source .venv/bin/activate
uv pip install wheel/sglang-0.0.0.dev11416+g92e8bb79e-py3-none-any.whl
uv pip install kernels==0.11.7 pymupdf==1.27.2.2
```

### Development Tools (from `.gitignore` — pytest, black, isort, ruff, mypy)

```bash
ruff check .                    # Lint
black .                         # Format
isort .                         # Sort imports
mypy infer.py                   # Type check
pytest                          # Run tests (when added)
```

### Inference

```bash
# Single image / image directory (SGLang)
python infer.py --image_dir ./examples/images --output_dir ./outputs --concurrency 8 --image_mode gundam

# PDF (SGLang, base mode only)
python infer.py --pdf ./document.pdf --output_dir ./outputs --concurrency 8 --image_mode base

# Transformers direct (single image)
python -c "
from transformers import AutoModel, AutoTokenizer
model = AutoModel.from_pretrained('baidu/Unlimited-OCR', trust_remote_code=True, torch_dtype=torch.bfloat16).eval().cuda()
tokenizer = AutoTokenizer.from_pretrained('baidu/Unlimited-OCR', trust_remote_code=True)
model.infer(tokenizer, prompt='<image>document parsing.', image_file='img.jpg', output_path='./out')
"
```

### SGLang Server (standalone)

```bash
python -m sglang.launch_server \
    --model baidu/Unlimited-OCR \
    --served-model-name Unlimited-OCR \
    --attention-backend fa3 \
    --page-size 1 \
    --mem-fraction-static 0.8 \
    --context-length 32768 \
    --enable-custom-logit-processor \
    --disable-overlap-schedule \
    --skip-server-warmup \
    --host 0.0.0.0 --port 10000
```

## Key Technical Details

- **Dependencies**: torch≥2.10, transformers≥4.57, sglang (bundled wheel), pymupdf, Pillow
- **GPU**: CUDA 12.9+, A100/H100 recommended; tested on Python 3.12
- **Context length**: 32768 tokens
- **Repetition suppression**: `no_repeat_ngram_size=35` with `ngram_window=128` (single) / `1024` (multi-page)
- **PDF preprocessing**: PyMuPDF (`fitz`) at 300 DPI; each page rendered to PNG then sent as separate request
- **Always** set `trust_remote_code=True` when loading the model from HuggingFace — the custom model code is required
- The SGLang server must be started with `--enable-custom-logit-processor` for repetition suppression to work
- **Code style**: PEP 8, 4-space indentation, type annotations on all function signatures

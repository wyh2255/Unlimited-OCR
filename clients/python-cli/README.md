# ocr-client (canonical source)

This is the canonical Python CLI for the Unlimited-OCR LAN gateway. The
console script `ocr-client` and the `python -m ocr_client` entry point both
come from this package.

The `ocr-client/` directory at the repo root is a thin build wrapper that
produces a pre-bundled wheel from this source — see `ocr-client/README.md`
(中文) for the legacy install instructions.

## Install (recommended)

```bash
# From this directory
pip install -e .
# or with rich progress bars
pip install -e ".[rich]"

# Then
ocr-client health
ocr-client upload my.pdf --watch
```

## Use as a library

```python
from ocr_client import api, progress

data = api.fetch_status("http://127.0.0.1:10001", token=None, task_id="abc123def456")
print(progress.print_status(None, data))
```

## Module layout

| File | Purpose |
|------|---------|
| `src/ocr_client/__init__.py` | Public surface; `__version__` |
| `src/ocr_client/__main__.py` | `python -m ocr_client` |
| `src/ocr_client/cli.py` | Subcommand handlers + argparse + `main()` |
| `src/ocr_client/api.py` | Low-level HTTP: `build_headers`, `check_resp`, `fetch_status` |
| `src/ocr_client/progress.py` | Rich / ASCII presentation + watch loops |

## Subcommands

| Cmd | Positional | Flags (besides `--server` / `--token`) |
|-----|------------|----------------------------------------|
| `upload` | `pdf` | `--image-mode {gundam,base}`, `--concurrency-hint 1..16`, `--out`, `--watch` |
| `status` | `task_id` | `--watch` |
| `download` | `task_id` | `--out` |
| `delete` | `task_id` | — |
| `health` | — | — |

## Environment variables

| Var | Default | Used by |
|-----|---------|---------|
| `OCR_SERVER` | `http://127.0.0.1:10001` | `--server` default |
| `OCR_API_TOKEN` | (none) | `--token` default |

## Wire protocol

See `API_CONTRACT.md` (中文, canonical) or `docs/api-contract-en.md` (English supplement)
at the repo root.

## Compatibility

- Python ≥ 3.10
- `requests` ≥ 2.31
- `rich` ≥ 13.7 (optional)

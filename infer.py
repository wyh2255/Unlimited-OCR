"""Backward-compat shim. Real implementation lives in `inference/cli.py`.

Usage (unchanged):
    python infer.py --pdf <file> --concurrency 8 --image_mode gundam
    python infer.py --image_dir <dir> --output_dir <dir>

After Phase 3, the canonical entry is:
    python -m inference.cli ...
"""
from inference.cli import main

if __name__ == "__main__":
    main()

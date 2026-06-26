"""Backward-compat shim. Real implementation lives in `inference/postprocess.py`.

Usage (unchanged):
    python postprocess_sglang.py --pdf <pdf> --input_dir <dir> [--output_dir <dir>]

After Phase 3, the canonical entry is:
    python -m inference.postprocess ...
"""
from inference.postprocess import main

if __name__ == "__main__":
    main()

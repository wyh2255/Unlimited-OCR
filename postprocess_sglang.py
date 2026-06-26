"""Backward-compat shim. Real implementation lives in `sglang/postprocess.py`.

Usage (unchanged):
    python postprocess_sglang.py --pdf <pdf> --input_dir <dir> [--output_dir <dir>]

After Phase 3, the canonical entry is:
    python -m sglang.postprocess ...
"""
from sglang.postprocess import main

if __name__ == "__main__":
    main()

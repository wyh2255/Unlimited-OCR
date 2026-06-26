"""Backward-compat shim. Real implementation lives in `model/ocr_pdf.py`.

Usage (unchanged):
    python ocr_pdf.py <pdf> [--no-page-split]

After Phase 3, the canonical entry is:
    python -m model.ocr_pdf ...
"""
from model.ocr_pdf import main

if __name__ == "__main__":
    main()

"""Shared PDF rendering helpers.

Centralizes the `fitz`-based PDF→PNG logic that was previously duplicated
across `ocr_pdf.py`, `infer.py`, and `postprocess_sglang.py`. Lives under
`model/` (will move to a shared `common/` location in Phase 3 if other
non-model paths need it).
"""

import os
import tempfile

import fitz

DEFAULT_DPI = 300


def pdf_to_images(pdf_path: str, dpi: int = DEFAULT_DPI, prefix: str = "pdf_ocr_") -> tuple[list[str], str]:
    """Render each PDF page to a PNG file at the given DPI.

    Returns ``(image_paths, tmp_dir)`` — the caller is responsible for
    cleaning up ``tmp_dir`` (typically via ``shutil.rmtree``).

    Args:
        pdf_path: path to the input PDF.
        dpi: render resolution. 300 matches the rest of the pipeline; 150
            is fine for quick previews; 600 is overkill.
        prefix: tempfile prefix; lets callers distinguish the source of
            the tmp dir when multiple modules run in the same process.
    """
    doc = fitz.open(pdf_path)
    tmp_dir = tempfile.mkdtemp(prefix=prefix)
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    images: list[str] = []
    try:
        for i, page in enumerate(doc):
            out = os.path.join(tmp_dir, f"page_{i + 1:04d}.png")
            page.get_pixmap(matrix=mat).save(out)
            images.append(out)
    finally:
        doc.close()
    return images, tmp_dir

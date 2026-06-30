"""Pandoc-based document conversion for OCR results.

Wraps `pandoc` subprocess calls to convert a result ZIP (`result.md` +
`images/`) into docx / html / pdf / latex. The `md` format is a plain copy
of the source ZIP (no pandoc invocation).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from functools import lru_cache
from typing import Tuple

SUPPORTED_FORMATS: Tuple[str, ...] = ("md", "docx", "html", "pdf", "latex")


class ConversionError(Exception):
    """Raised when pandoc fails or input is invalid."""


@lru_cache(maxsize=1)
def _pandoc_version() -> Tuple[int, int]:
    """Return (major, minor) of the installed pandoc. (0, 0) if detection fails."""
    try:
        out = subprocess.check_output(
            ["pandoc", "--version"], text=True, timeout=10, stderr=subprocess.STDOUT
        )
    except Exception:
        return (0, 0)
    first_line = out.splitlines()[0] if out else ""
    m = re.search(r"(\d+)\.(\d+)", first_line)
    if not m:
        return (0, 0)
    return (int(m.group(1)), int(m.group(2)))


def _html_embed_flags() -> list:
    """Return the correct HTML resource-embedding flags for this pandoc version.

    pandoc >= 2.19 introduced `--embed-resources` as the replacement for the
    deprecated `--self-contained` (which was removed in pandoc 3.x). We pick
    the flag that the installed pandoc actually supports so the same code
    works on pandoc 2.12 (old conda build) and pandoc 3.x (modern apt).
    """
    major, minor = _pandoc_version()
    if (major, minor) >= (2, 19):
        return ["--embed-resources", "--standalone"]
    return ["--self-contained"]


def _build_pandoc_cmd(
    md_path: str, out_path: str, fmt: str, tmp_dir: str, pdf_engine: str
) -> list:
    """Build the pandoc command for the requested format."""
    cmd = ["pandoc", md_path, "-o", out_path, "--resource-path", tmp_dir]
    if fmt == "html":
        cmd += _html_embed_flags()
    elif fmt == "latex":
        cmd += ["--standalone"]
    elif fmt == "pdf":
        cmd += ["--standalone", "--pdf-engine", pdf_engine]
    elif fmt == "docx":
        pass
    return cmd


def convert_result(
    zip_path: str, fmt: str, out_path: str, pdf_engine: str = "weasyprint"
) -> str:
    """Convert a result ZIP into the target format and write to `out_path`.

    - `fmt="md"`: copies `zip_path` to `out_path` (no pandoc call).
    - Other formats: extracts the ZIP to a temp dir, runs pandoc with
      `--resource-path` so `images/*.jpg` references resolve, writes the
      converted file to `out_path`, then cleans up the temp dir.

    Raises `ConversionError` on any failure. Returns `out_path` on success.
    """
    if fmt not in SUPPORTED_FORMATS:
        raise ConversionError(f"unsupported format: {fmt}")
    if fmt == "md":
        shutil.copy(zip_path, out_path)
        return out_path

    with tempfile.TemporaryDirectory(prefix="uocr_convert_") as tmp_dir:
        try:
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(tmp_dir)
        except zipfile.BadZipFile as e:
            raise ConversionError(f"invalid zip: {e}")

        md_path = os.path.join(tmp_dir, "result.md")
        if not os.path.isfile(md_path):
            raise ConversionError("zip missing result.md")

        cmd = _build_pandoc_cmd(md_path, out_path, fmt, tmp_dir, pdf_engine)
        try:
            subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                timeout=180,
            )
        except subprocess.CalledProcessError as e:
            stderr = e.stderr.decode(errors="replace") if e.stderr else ""
            raise ConversionError(f"pandoc failed: {stderr.strip()}")
        except subprocess.TimeoutExpired:
            raise ConversionError("pandoc conversion timeout (180s)")

    if not os.path.isfile(out_path):
        raise ConversionError(f"pandoc produced no output at {out_path}")
    return out_path

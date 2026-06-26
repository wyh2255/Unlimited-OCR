#!/usr/bin/env bash
# Build a pre-bundled `ocr-client` wheel from `clients/python-cli/`.
#
# The bundled wheel is the standard way users on laptops without a GPU
# install the CLI: `uv tool install ocr-client/dist/ocr_client-*.whl`.
#
# This script is idempotent — re-running rebuilds the wheel.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC_DIR="${REPO_ROOT}/clients/python-cli"
OUT_DIR="${REPO_ROOT}/ocr-client/dist"

if [[ ! -d "${SRC_DIR}" ]]; then
    echo "ERROR: source dir not found: ${SRC_DIR}" >&2
    exit 1
fi

mkdir -p "${OUT_DIR}"

# Prefer uv (faster, no extra venv needed), fall back to python -m build
if command -v uv >/dev/null 2>&1; then
    echo "[build_ocr_client] using uv"
    (cd "${SRC_DIR}" && uv build --out-dir "${OUT_DIR}")
else
    echo "[build_ocr_client] uv not found; falling back to python -m build"
    (cd "${SRC_DIR}" && python -m build --outdir "${OUT_DIR}")
fi

echo "[build_ocr_client] wheel(s) in ${OUT_DIR}:"
ls -lh "${OUT_DIR}"/*.whl 2>/dev/null || true

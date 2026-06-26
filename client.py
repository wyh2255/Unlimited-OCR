"""Backward-compat shim. Real implementation lives in
`clients/python-cli/src/ocr_client/cli.py`.

After Phase 4, the canonical entry is one of:
    python -m ocr_client ...
    ocr-client ...                       (after `pip install -e clients/python-cli`)
    uv tool install clients/python-cli  (alternative install)
"""
from ocr_client.cli import main

if __name__ == "__main__":
    main()

"""Unlimited-OCR HTTP CLI client.

Single source of truth for the `ocr-client` console script. The bundled
`ocr-client/` directory in the repo root is a packaging wrapper around this
package (see `ocr-client/README.md`).

Public surface:
- `main(argv=None) -> int` — the CLI entry point
- `api`, `progress` submodules — exposed for advanced use
"""

from .cli import main, build_parser, cmd_health, cmd_upload, cmd_status, cmd_download, cmd_delete

__version__ = "0.2.0"
__all__ = [
    "main",
    "build_parser",
    "cmd_health",
    "cmd_upload",
    "cmd_status",
    "cmd_download",
    "cmd_delete",
]

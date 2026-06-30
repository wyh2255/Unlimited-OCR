"""Token → owner mapping for multi-user mode.

Reads a JSON config file (`~/.ocr_tokens.json` by default) that maps each
bearer token to an owner string. The file is hot-reloaded on mtime change.
When the file is absent, falls back to single-token mode using
`OCR_API_TOKEN` with owner `"self"`.

Config file format:

    {
      "tokens": [
        {"token": "t1xxx", "owner": "alice"},
        {"token": "t2xxx", "owner": "bob"}
      ]
    }
"""

from __future__ import annotations

import json
import os
import threading
from typing import Optional


class UserRegistry:
    """Token → owner lookup with mtime-based hot reload and single-token fallback."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._path: str = ""
        self._mtime: float = 0.0
        self._tokens: dict[str, str] = {}
        self._single_token: Optional[str] = None

    def configure(self, tokens_file: Optional[str], env_token: Optional[str]) -> None:
        """Set the config file path and the fallback single token."""
        with self._lock:
            self._path = tokens_file or os.path.expanduser("~/.ocr_tokens.json")
            self._single_token = env_token
            self._mtime = 0.0
            self._tokens = {}
            self._reload_if_needed()

    def _reload_if_needed(self) -> None:
        """Re-read the config file if its mtime changed. Caller must hold the lock."""
        if not os.path.isfile(self._path):
            return
        try:
            mtime = os.path.getmtime(self._path)
        except OSError:
            return
        if mtime == self._mtime:
            return
        try:
            with open(self._path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            new_tokens: dict[str, str] = {}
            for item in data.get("tokens", []):
                tok = item.get("token")
                own = item.get("owner")
                if tok and own:
                    new_tokens[tok] = own
            self._tokens = new_tokens
            self._mtime = mtime
        except (OSError, ValueError, json.JSONDecodeError):
            pass

    def lookup(self, token: str) -> Optional[str]:
        """Return the owner for a token, or None if unknown."""
        with self._lock:
            self._reload_if_needed()
            if self._tokens:
                return self._tokens.get(token)
            if self._single_token and token == self._single_token:
                return "self"
            return None

    def is_multi_user_mode(self) -> bool:
        """True when a non-empty tokens file is loaded."""
        with self._lock:
            self._reload_if_needed()
            return bool(self._tokens)

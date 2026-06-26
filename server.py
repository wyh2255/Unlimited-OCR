"""Backward-compat shim. Real implementation lives in `gateway/server.py`.

Usage (unchanged):
    python server.py --port 10001 --cors-origin '*'

After Phase 3, the canonical entry is:
    python -m gateway.server ...
"""
from gateway.server import main

if __name__ == "__main__":
    main()

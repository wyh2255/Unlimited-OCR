"""Bearer-token auth dependency.

`get_token` is a FastAPI dependency used on every endpoint except
`/api/v1/health`.
"""

from __future__ import annotations

import secrets
from typing import Optional

from fastapi import Header, HTTPException

from .state import STATE


def get_token(authorization: Optional[str] = Header(default=None)) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="invalid token")
    candidate = authorization[len("Bearer "):]
    if not STATE.token or not secrets.compare_digest(candidate, STATE.token):
        raise HTTPException(status_code=401, detail="invalid token")
    return candidate

"""Bearer-token auth dependency.

`get_token` is a FastAPI dependency used on every endpoint except
`/api/v1/health`. It returns the owner string (looked up from the
UserRegistry), not the raw token.
"""

from __future__ import annotations

from typing import Optional

from fastapi import Header, HTTPException

from .state import STATE


def get_token(authorization: Optional[str] = Header(default=None)) -> str:
    """Validate the bearer token and return the owner it maps to."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="invalid token")
    candidate = authorization[len("Bearer "):]
    owner = STATE.users.lookup(candidate)
    if owner is None:
        raise HTTPException(status_code=401, detail="invalid token")
    return owner

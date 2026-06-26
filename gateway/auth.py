"""Bearer-token auth and CORS middleware configuration.

`get_token` is a FastAPI dependency used on every endpoint except
`/api/v1/health`. `configure_cors` is called from `gateway.server.main()`
before the first request.
"""

from __future__ import annotations

import secrets
from typing import Optional

from fastapi import Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .state import STATE


def get_token(authorization: Optional[str] = Header(default=None)) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="invalid token")
    candidate = authorization[len("Bearer "):]
    if not STATE.token or not secrets.compare_digest(candidate, STATE.token):
        raise HTTPException(status_code=401, detail="invalid token")
    return candidate


_CORS_ORIGINS: list[str] = ["*"]


def configure_cors(origins: list[str]) -> None:
    """Reconfigure the CORS middleware. Must be called before the first request.

    FastAPI builds the middleware stack at first request, so adding CORS via
    `app.add_middleware(...)` after construction is silently ignored. The
    `clear → reset stack → add` dance below is required to make the change
    take effect.
    """
    from .server import app  # late import to avoid circular at module load
    global _CORS_ORIGINS
    _CORS_ORIGINS = origins or ["*"]
    app.user_middleware = [
        m for m in app.user_middleware if m.cls is not CORSMiddleware
    ]
    app.middleware_stack = None
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition"],
    )


def cors_origins() -> list[str]:
    return list(_CORS_ORIGINS)

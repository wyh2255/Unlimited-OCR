"""Low-level HTTP helpers for the Unlimited-OCR gateway client.

No presentation / no rich. Just requests → dict (or sentinel for transport errors).
"""
from __future__ import annotations

from typing import Any

import requests


def build_headers(token: str | None) -> dict[str, str]:
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def check_resp(resp: requests.Response) -> dict[str, Any] | None:
    """Parse a response. Returns {} on 204, raises RuntimeError on 4xx/5xx."""
    if resp.status_code == 204:
        return {}
    try:
        data = resp.json()
    except ValueError:
        data = {"detail": resp.text or f"HTTP {resp.status_code}"}
    if not resp.ok:
        detail = data.get("detail") if isinstance(data, dict) else None
        if detail is None:
            detail = resp.text or f"HTTP {resp.status_code}"
        raise RuntimeError(f"HTTP {resp.status_code}: {detail}")
    return data


def fetch_status(server: str, token: str | None, task_id: str) -> dict[str, Any] | None:
    """Single GET /api/v1/tasks/{id}. Returns None on hard failure, sentinel
    `{"__error__": "..."}` on transport errors (so polling loops can show
    'poll error' without crashing)."""
    try:
        resp = requests.get(
            f"{server}/api/v1/tasks/{task_id}",
            headers=build_headers(token),
            timeout=10.0,
        )
    except requests.RequestException as e:
        return {"__error__": str(e)}
    return check_resp(resp)


def whoami(server: str, token: str | None) -> dict[str, Any] | None:
    """GET /api/v1/me — returns {'owner': '...'}."""
    r = requests.get(
        f"{server}/api/v1/me",
        headers=build_headers(token),
        timeout=10.0,
    )
    return check_resp(r)


def list_tasks(server: str, token: str | None, scope: str = "mine") -> dict[str, Any] | None:
    """GET /api/v1/tasks?scope=mine|all — returns {'tasks': [...], 'count': N, 'scope': '...'}."""
    r = requests.get(
        f"{server}/api/v1/tasks",
        params={"scope": scope},
        headers=build_headers(token),
        timeout=10.0,
    )
    return check_resp(r)

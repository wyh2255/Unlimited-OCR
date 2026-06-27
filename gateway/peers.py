from __future__ import annotations

import dataclasses
from typing import Optional

import requests


@dataclasses.dataclass
class PeerConfig:
    url: str       # "http://192.168.1.100:10001"
    token: str


def _make_session() -> requests.Session:
    session = requests.Session()
    session.trust_env = False  # avoid proxy interference (project convention)
    return session


def probe_peer(peer: PeerConfig, timeout: float = 3.0) -> Optional[dict]:
    """GET /api/v1/health of a peer. Returns dict on success, None on failure/timeout."""
    session = _make_session()
    try:
        resp = session.get(
            f"{peer.url}/api/v1/health",
            headers={"Accept": "application/json"},
            timeout=timeout,
        )
        if resp.status_code == 200:
            return resp.json()
        return None
    except requests.RequestException:
        return None


def select_best_backend(self_health: dict, peers_health: dict[str, Optional[dict]]) -> str:
    """Pick the best backend.

    Returns "self" or a peer URL string.

    Selection criteria:
    1. Filter out peers with None health (probe failed)
    2. Order all candidates (self + available peers):
       a. idle (current_task is None or queue_length == 0) preferred
       b. shorter queue_length preferred
       c. larger free_mb (from gpu.free_mb or self.free_mb) preferred
    3. Tiebreak: prefer "self"
    """
    candidates = [("self", self_health)]
    for url, health in peers_health.items():
        if health is not None:
            candidates.append((url, health))

    if not candidates:
        return "self"

    def score(item):
        name, h = item
        # - idle: current_task is None → weight 0, else 1
        is_busy = 1 if h.get("current_task") is not None else 0
        # queue length (smaller is better, use as secondary)
        qlen = h.get("queue_length", 0)
        # free memory (bigger is better)
        gpu = h.get("gpu", {})
        free_mb = gpu.get("free_mb", 0) if isinstance(gpu, dict) else 0
        # self preference (0 = self, 1 = peer) as last tiebreak
        self_pref = 0 if name == "self" else 1
        return (is_busy, qlen, -free_mb, self_pref)

    candidates.sort(key=score)
    return candidates[0][0]


def proxy_upload(
    peer: PeerConfig,
    content: bytes,
    image_mode: str,
    concurrency_hint: Optional[int],
) -> requests.Response:
    """Forward a PDF upload to a peer via multipart POST."""
    session = _make_session()
    files = {"file": ("input.pdf", content, "application/pdf")}
    data: dict[str, str] = {"image_mode": image_mode}
    if concurrency_hint is not None:
        data["concurrency_hint"] = str(concurrency_hint)

    resp = session.post(
        f"{peer.url}/api/v1/tasks",
        files=files,
        data=data,
        headers={"Authorization": f"Bearer {peer.token}"},
        timeout=120.0,  # generous; includes SGLang warmup
    )
    return resp


def proxy_request(peer: PeerConfig, method: str, path: str) -> requests.Response:
    """Proxy a GET/DELETE request to a peer.

    `path` should be like "/api/v1/tasks/abc123def456".
    """
    session = _make_session()
    resp = session.request(
        method=method,
        url=f"{peer.url}{path}",
        headers={
            "Authorization": f"Bearer {peer.token}",
            "Accept": "application/json",
        },
        timeout=30.0,
    )
    return resp

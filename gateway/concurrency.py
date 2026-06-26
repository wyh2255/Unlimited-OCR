"""GPU tier detection. Shells out to `nvidia-smi` (no GPU-side deps)."""

from __future__ import annotations

import subprocess


def detect_concurrency(gpu_index: int = 0) -> int:
    """Return 8 / 4 / 2 based on free GPU memory. Falls back to 2 on error."""
    cmd = [
        "nvidia-smi",
        "--query-gpu=memory.free",
        "--format=csv,noheader,nounits",
        "-i",
        str(gpu_index),
    ]
    try:
        out = subprocess.check_output(cmd, text=True, timeout=10).strip()
        free_mb = int(out.splitlines()[0])
    except Exception:
        return 2
    free_gb = free_mb / 1024.0
    if free_gb >= 30.0:
        return 8
    if free_gb >= 10.0:
        return 4
    return 2


def _get_gpu_info(gpu_index: int) -> dict:
    cmd = [
        "nvidia-smi",
        "--query-gpu=name,memory.total,memory.free,memory.used",
        "--format=csv,noheader,nounits",
        "-i",
        str(gpu_index),
    ]
    try:
        out = subprocess.check_output(cmd, text=True, timeout=10).strip()
        parts = [p.strip() for p in out.splitlines()[0].split(",")]
        return {
            "name": parts[0],
            "total_mb": int(parts[1]),
            "free_mb": int(parts[2]),
            "used_mb": int(parts[3]),
        }
    except Exception:
        return {"name": "unknown", "total_mb": 0, "free_mb": 0, "used_mb": 0}

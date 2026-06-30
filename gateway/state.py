"""Mutable in-memory state for the FastAPI gateway.

Holds the singleton `STATE` object (per-task dict, queue, workdir, token)
and the `TaskState` dataclass with its JSON serializer. No FastAPI imports
here so other gateway modules can import this without triggering app
construction.
"""

from __future__ import annotations

import queue
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from .peers import PeerConfig


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class TaskState:
    task_id: str
    status: str = "queued"
    progress: float = 0.0
    current_page: int = 0
    total_pages: int = 0
    image_mode: str = "base"
    concurrency: int = 0
    error: Optional[str] = None
    created_at: str = field(default_factory=_now_iso)
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    pdf_path: str = ""
    work_subdir: str = ""
    backend_url: str = ""


def _task_to_dict(task: TaskState) -> dict:
    d: dict = {
        "task_id": task.task_id,
        "status": task.status,
        "progress": round(task.progress, 4),
        "current_page": task.current_page,
        "total_pages": task.total_pages,
        "image_mode": task.image_mode,
        "concurrency": task.concurrency,
        "error": task.error,
        "created_at": task.created_at,
        "started_at": task.started_at,
        "finished_at": task.finished_at,
    }
    if task.backend_url:
        d["backend_url"] = task.backend_url
    return d


class _State:
    def __init__(self) -> None:
        self.workdir: str = "./api_workdir"
        self.model_dir: str = "./Unlimited-OCR"
        self.gpu_index: int = 0
        self.token: str = ""
        self.tasks: dict[str, TaskState] = {}
        self.lock = threading.Lock()
        self.queue: "queue.Queue[str]" = queue.Queue()
        self.logs_dir: str = ""
        self.peers: list[PeerConfig] = []
        self.proxied: dict[str, str] = {}
        self.pandoc_pdf_engine: str = "weasyprint"


STATE = _State()

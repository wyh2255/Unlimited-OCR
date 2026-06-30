"""SQLite-backed task persistence.

Stores task metadata in `api_workdir/tasks.db` so the task list survives
server restarts. Uses stdlib `sqlite3` (no new dependency). All writes are
serialized by a process-level lock; reads are lock-free after open.

Schema mirrors the stable fields of `TaskState` (those worth recovering
across restarts). Transient fields (`pdf_path`, `work_subdir`) are NOT
persisted because the tmp dir is cleared on task completion or becomes
stale on restart.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .state import TaskState


_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    status TEXT NOT NULL,
    pdf_name TEXT NOT NULL,
    image_mode TEXT NOT NULL,
    concurrency INTEGER NOT NULL,
    progress REAL NOT NULL,
    current_page INTEGER NOT NULL,
    total_pages INTEGER NOT NULL,
    error TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    backend_url TEXT
);
"""


class Persistence:
    """CRUD wrapper over `tasks.db`."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        with self._lock:
            conn = sqlite3.connect(db_path)
            conn.executescript(_SCHEMA)
            conn.commit()
            conn.close()

    def save_task(self, task: TaskState) -> None:
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            conn.execute(
                """INSERT OR REPLACE INTO tasks
                   (task_id, owner, status, pdf_name, image_mode, concurrency,
                    progress, current_page, total_pages, error,
                    created_at, started_at, finished_at, backend_url)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    task.task_id,
                    task.owner,
                    task.status,
                    task.pdf_name,
                    task.image_mode,
                    task.concurrency,
                    task.progress,
                    task.current_page,
                    task.total_pages,
                    task.error,
                    task.created_at,
                    task.started_at,
                    task.finished_at,
                    task.backend_url or "",
                ),
            )
            conn.commit()
            conn.close()

    def load_all(self) -> list:
        """Load all tasks from disk. Returns list of TaskState."""
        from .state import TaskState

        with self._lock:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM tasks").fetchall()
            conn.close()
        tasks: list = []
        for r in rows:
            tasks.append(
                TaskState(
                    task_id=r["task_id"],
                    owner=r["owner"],
                    status=r["status"],
                    pdf_name=r["pdf_name"],
                    image_mode=r["image_mode"],
                    concurrency=r["concurrency"],
                    progress=r["progress"],
                    current_page=r["current_page"],
                    total_pages=r["total_pages"],
                    error=r["error"],
                    created_at=r["created_at"],
                    started_at=r["started_at"],
                    finished_at=r["finished_at"],
                    backend_url=r["backend_url"] or "",
                )
            )
        return tasks

    def delete_task(self, task_id: str) -> None:
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            conn.execute("DELETE FROM tasks WHERE task_id=?", (task_id,))
            conn.commit()
            conn.close()

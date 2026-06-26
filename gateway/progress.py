"""Per-task progress poller and result-zip helper.

The poller runs in a daemon thread (started by `gateway.tasks._process_task`)
and updates `task.current_page` / `task.progress` by counting `.md` files
in the SGLang output dir every 0.5 s.
"""

from __future__ import annotations

import os
import threading
import zipfile

from .state import STATE, TaskState

POLL_INTERVAL_S = 0.5


def _poll_progress(task: TaskState, output_dir: str, stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        try:
            entries = os.listdir(output_dir)
        except (FileNotFoundError, OSError):
            entries = []
        done = sum(
            1 for f in entries
            if f.endswith(".md") and f != "result.md"
        )
        with STATE.lock:
            if done > task.current_page:
                task.current_page = done
                if task.total_pages > 0:
                    task.progress = min(done / task.total_pages, 0.99)
        stop_event.wait(POLL_INTERVAL_S)


def _zip_directory(src_dir: str, zip_path: str) -> None:
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(src_dir):
            for fname in files:
                abs_path = os.path.join(root, fname)
                rel_path = os.path.relpath(abs_path, src_dir)
                zf.write(abs_path, rel_path)

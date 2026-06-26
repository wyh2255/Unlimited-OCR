"""Task processing pipeline and the FIFO worker loop.

`_process_task` is the heart of the gateway: open PDF → detect concurrency →
run SGLang batch via `sglang.batch.run_inference` → run `sglang.postprocess`
via subprocess → zip result → cleanup.

`_worker_loop` reads `task_id`s from `STATE.queue` and feeds them to
`_process_task`. It runs in a single daemon thread started by
`gateway.server.main()`.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading

import fitz

from sglang.batch import run_inference

from .concurrency import detect_concurrency
from .progress import _poll_progress, _zip_directory
from .state import STATE, TaskState, _now_iso


def _process_task(task: TaskState) -> None:
    with STATE.lock:
        task.status = "running"
        task.started_at = _now_iso()

    try:
        doc = fitz.open(task.pdf_path)
        total_pages = doc.page_count
        doc.close()
    except Exception as e:
        with STATE.lock:
            task.status = "failed"
            task.error = f"failed to read PDF: {e}"
            task.finished_at = _now_iso()
        return

    with STATE.lock:
        task.total_pages = total_pages
        if task.concurrency == 0:
            task.concurrency = detect_concurrency(STATE.gpu_index)

    sglang_dir = os.path.join(task.work_subdir, "sglang")
    cleaned_dir = os.path.join(task.work_subdir, "cleaned")
    server_log = os.path.join(STATE.logs_dir, f"{task.task_id}_sglang.log")
    os.makedirs(sglang_dir, exist_ok=True)
    os.makedirs(cleaned_dir, exist_ok=True)

    stop_event = threading.Event()
    poller = threading.Thread(
        target=_poll_progress,
        args=(task, sglang_dir, stop_event),
        daemon=True,
    )
    poller.start()

    try:
        run_inference(
            pdf=task.pdf_path,
            output_dir=sglang_dir,
            concurrency=task.concurrency,
            model_dir=STATE.model_dir,
            gpu=str(STATE.gpu_index),
            image_mode="base",
            server_log=server_log,
        )

        stop_event.set()
        poller.join(timeout=2)

        with STATE.lock:
            task.current_page = task.total_pages
            task.progress = 0.95

        proc = subprocess.run(
            [
                sys.executable, "-m", "sglang.postprocess",
                "--pdf", task.pdf_path,
                "--input_dir", sglang_dir,
                "--output_dir", cleaned_dir,
            ],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"postprocess failed (code {proc.returncode}): "
                f"{(proc.stderr or proc.stdout).strip()}"
            )

        with STATE.lock:
            task.progress = 0.99

        zip_path = os.path.join(STATE.workdir, "outputs", f"{task.task_id}.zip")
        os.makedirs(os.path.dirname(zip_path), exist_ok=True)
        _zip_directory(cleaned_dir, zip_path)

        shutil.rmtree(task.work_subdir, ignore_errors=True)

        with STATE.lock:
            task.status = "completed"
            task.progress = 1.0
            task.finished_at = _now_iso()
    except Exception as e:
        stop_event.set()
        poller.join(timeout=2)
        with STATE.lock:
            task.status = "failed"
            task.error = str(e)
            task.finished_at = _now_iso()
        shutil.rmtree(task.work_subdir, ignore_errors=True)


def _worker_loop() -> None:
    while True:
        task_id = STATE.queue.get()
        try:
            with STATE.lock:
                task = STATE.tasks.get(task_id)
            if task is None:
                continue
            _process_task(task)
        except Exception as e:
            with STATE.lock:
                t = STATE.tasks.get(task_id)
                if t is not None and t.status == "running":
                    t.status = "failed"
                    t.error = f"worker error: {e}"
                    t.finished_at = _now_iso()
        finally:
            STATE.queue.task_done()

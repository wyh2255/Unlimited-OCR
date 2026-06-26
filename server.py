"""
FastAPI HTTP gateway for Unlimited-OCR (API contract v1.0).

Required dependencies (install via uv pip into the existing venv):
    fastapi>=0.110
    uvicorn[standard]>=0.27
    python-multipart>=0.0.9
    pymupdf>=1.24
    Pillow>=10.0

Implicit dependencies (assumed already in the venv):
    torch
    requests
    sglang (local wheel under wheel/)
    kernels==0.11.7
    infer (local module providing run_inference)
    postprocess_sglang (local CLI script, invoked via subprocess)

CLI:
    export OCR_API_TOKEN=...        # optional; if unset, a token is generated and printed
    python server.py [--host HOST] [--port PORT] [--workdir DIR]
"""

from __future__ import annotations

import argparse
import os
import queue
import secrets
import shutil
import subprocess
import sys
import threading
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import fitz
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse

from infer import run_inference


MAX_PDF_BYTES = 200 * 1024 * 1024
POLL_INTERVAL_S = 0.5
DEFAULT_MODEL_DIR = "./Unlimited-OCR"


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


def _task_to_dict(task: TaskState) -> dict:
    return {
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


def detect_concurrency(gpu_index: int = 0) -> int:
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


class _State:
    def __init__(self) -> None:
        self.workdir: str = "./api_workdir"
        self.model_dir: str = DEFAULT_MODEL_DIR
        self.gpu_index: int = 0
        self.token: str = ""
        self.tasks: dict[str, TaskState] = {}
        self.lock = threading.Lock()
        self.queue: "queue.Queue[str]" = queue.Queue()
        self.logs_dir: str = ""


STATE = _State()


def get_token(authorization: Optional[str] = Header(default=None)) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="invalid token")
    candidate = authorization[len("Bearer "):]
    if not STATE.token or not secrets.compare_digest(candidate, STATE.token):
        raise HTTPException(status_code=401, detail="invalid token")
    return candidate


app = FastAPI(title="Unlimited-OCR API", version="1.0")


@app.get("/api/v1/health")
def health() -> dict:
    with STATE.lock:
        current_task_id: Optional[str] = None
        for t in STATE.tasks.values():
            if t.status == "running":
                current_task_id = t.task_id
                break
        queue_length = STATE.queue.qsize()
    return {
        "status": "ok",
        "gpu": _get_gpu_info(STATE.gpu_index),
        "concurrency_recommended": detect_concurrency(STATE.gpu_index),
        "queue_length": queue_length,
        "current_task": current_task_id,
    }


@app.post("/api/v1/tasks", status_code=202, dependencies=[Depends(get_token)])
async def create_task(
    file: UploadFile = File(...),
    image_mode: str = Form("base"),
    concurrency_hint: Optional[int] = Form(None),
):
    if concurrency_hint is not None and not (1 <= concurrency_hint <= 16):
        raise HTTPException(status_code=400, detail="concurrency_hint must be 1-16")
    if image_mode not in ("gundam", "base"):
        raise HTTPException(status_code=400, detail="image_mode must be 'gundam' or 'base'")

    content = await file.read()
    if len(content) > MAX_PDF_BYTES:
        raise HTTPException(status_code=400, detail="PDF exceeds 200 MB")
    if not content.startswith(b"%PDF-"):
        raise HTTPException(status_code=400, detail="uploaded file is not a valid PDF")

    task_id = uuid.uuid4().hex[:12]
    work_subdir = os.path.join(STATE.workdir, "tmp", task_id)
    os.makedirs(work_subdir, exist_ok=True)
    pdf_path = os.path.join(work_subdir, "input.pdf")
    with open(pdf_path, "wb") as fh:
        fh.write(content)

    task = TaskState(
        task_id=task_id,
        image_mode="base",
        concurrency=int(concurrency_hint) if concurrency_hint else 0,
        pdf_path=pdf_path,
        work_subdir=work_subdir,
    )
    with STATE.lock:
        STATE.tasks[task_id] = task
    STATE.queue.put(task_id)

    return {
        "task_id": task_id,
        "status": "queued",
        "image_mode": "base",
        "concurrency_hint": concurrency_hint,
    }


@app.get("/api/v1/tasks/{task_id}", dependencies=[Depends(get_token)])
def get_task(task_id: str) -> dict:
    with STATE.lock:
        task = STATE.tasks.get(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="task not found")
        return _task_to_dict(task)


@app.get("/api/v1/tasks/{task_id}/download", dependencies=[Depends(get_token)])
def download_task(task_id: str):
    with STATE.lock:
        task = STATE.tasks.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    if task.status == "failed":
        raise HTTPException(status_code=410, detail="task failed; no zip available")
    if task.status != "completed":
        raise HTTPException(status_code=404, detail="task not completed")
    zip_path = os.path.join(STATE.workdir, "outputs", f"{task_id}.zip")
    if not os.path.isfile(zip_path):
        raise HTTPException(status_code=410, detail="zip missing")
    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=f"{task_id}.zip",
    )


@app.delete("/api/v1/tasks/{task_id}", dependencies=[Depends(get_token)])
def delete_task(task_id: str) -> Response:
    with STATE.lock:
        task = STATE.tasks.pop(task_id, None)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")

    zip_path = os.path.join(STATE.workdir, "outputs", f"{task_id}.zip")
    tmp_dir = os.path.join(STATE.workdir, "tmp", task_id)
    if os.path.isfile(zip_path):
        try:
            os.remove(zip_path)
        except OSError:
            pass
    if os.path.isdir(tmp_dir):
        shutil.rmtree(tmp_dir, ignore_errors=True)
    log_path = os.path.join(STATE.logs_dir, f"{task_id}_sglang.log")
    if os.path.isfile(log_path):
        try:
            os.remove(log_path)
        except OSError:
            pass
    return Response(status_code=204)


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
                sys.executable, "postprocess_sglang.py",
                "--pdf", task.pdf_path,
                "--input_dir", sglang_dir,
                "--output_dir", cleaned_dir,
            ],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"postprocess_sglang failed (code {proc.returncode}): "
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


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="FastAPI gateway for Unlimited-OCR (API contract v1.0).",
    )
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=10001)
    parser.add_argument("--workdir", default="./api_workdir")
    parser.add_argument("--model-dir", default=DEFAULT_MODEL_DIR)
    parser.add_argument("--gpu", type=int, default=0)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    STATE.workdir = os.path.abspath(args.workdir)
    STATE.model_dir = os.path.abspath(args.model_dir)
    STATE.gpu_index = args.gpu

    os.makedirs(os.path.join(STATE.workdir, "tmp"), exist_ok=True)
    os.makedirs(os.path.join(STATE.workdir, "outputs"), exist_ok=True)
    STATE.logs_dir = os.path.join(STATE.workdir, "logs")
    os.makedirs(STATE.logs_dir, exist_ok=True)

    token = os.environ.get("OCR_API_TOKEN", "").strip()
    if not token:
        token = secrets.token_urlsafe(24)
        print(f"[server] OCR_API_TOKEN not set; generated token: {token}", flush=True)
    STATE.token = token

    worker = threading.Thread(target=_worker_loop, daemon=True)
    worker.start()

    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()

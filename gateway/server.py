"""FastAPI app, HTTP endpoints, CLI parser, and `main()` entry point."""

from __future__ import annotations

import argparse
import os
import secrets
import shutil
import threading
import uuid
from typing import Optional

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .auth import get_token
from .concurrency import _get_gpu_info, detect_concurrency
from .state import STATE, TaskState, _now_iso, _task_to_dict
from .tasks import _worker_loop


MAX_PDF_BYTES = 200 * 1024 * 1024
DEFAULT_MODEL_DIR = "./Unlimited-OCR"

app = FastAPI(title="Unlimited-OCR API", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)


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


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="FastAPI gateway for Unlimited-OCR (API contract v1.0).",
    )
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=10001)
    parser.add_argument("--workdir", default="./api_workdir")
    parser.add_argument("--model-dir", default=DEFAULT_MODEL_DIR)
    parser.add_argument("--gpu", type=int, default=0)
    parser.add_argument(
        "--cors-origin",
        action="append",
        default=None,
        help=(
            "CORS allow-origin. May be passed multiple times. "
            "Use '*' for any (LAN default). Example: --cors-origin http://192.168.1.10:5173"
        ),
    )
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

    origins = args.cors_origin or ["*"]
    app.user_middleware = [
        m for m in app.user_middleware if m.cls is not CORSMiddleware
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition"],
    )
    print(f"[server] CORS allow_origins={origins}", flush=True)

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

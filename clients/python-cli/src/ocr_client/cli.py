"""CLI for the Unlimited-OCR gateway client.

Subcommands: upload, status, download, delete, health.

Module layout:
  - api.py: low-level HTTP helpers (build_headers, check_resp, fetch_status)
  - progress.py: rich/ASCII presentation + watch loops
  - cli.py: this file — subcommand handlers + argparse + main()
"""
from __future__ import annotations

import argparse
import os
import sys
import zipfile
from pathlib import Path
from typing import Any

import requests

from . import api, progress
from .api import build_headers, check_resp
from .progress import (
    _err,
    _print,
    console_or_none,
    ensure_status_terminal,
    print_status,
    watch_task,
    watch_with_progress,
)


DEFAULT_SERVER = "http://127.0.0.1:10001"
DOWNLOAD_CHUNK = 64 * 1024
HTTP_TIMEOUT = (10.0, None)


def cmd_health(args: argparse.Namespace) -> int:
    console = console_or_none()
    server = args.server.rstrip("/")
    try:
        resp = requests.get(f"{server}/api/v1/health", timeout=HTTP_TIMEOUT[0])
    except requests.RequestException as e:
        _err(console, f"cannot reach {server}: {e}")
        return 2
    data = check_resp(resp)
    if data is None:
        return 1
    if console is not None:
        console.print_json(data=data)
    else:
        import json as _json
        print(_json.dumps(data, indent=2, ensure_ascii=False))
    return 0


def cmd_upload(args: argparse.Namespace) -> int:
    console = console_or_none()
    server = args.server.rstrip("/")
    pdf_path = Path(args.pdf)
    if not pdf_path.is_file():
        _err(console, f"file not found: {pdf_path}")
        return 2

    data: dict[str, str] = {"image_mode": args.image_mode}
    if args.concurrency_hint is not None:
        data["concurrency_hint"] = str(args.concurrency_hint)

    try:
        with pdf_path.open("rb") as fh:
            resp = requests.post(
                f"{server}/api/v1/tasks",
                files={"file": (pdf_path.name, fh, "application/pdf")},
                data=data,
                headers=build_headers(args.token),
                timeout=60.0,
            )
    except requests.RequestException as e:
        _err(console, f"upload failed: {e}")
        return 2

    payload = check_resp(resp)
    if payload is None:
        return 1
    task_id = payload.get("task_id")
    if not task_id:
        _err(console, f"server returned no task_id: {payload}")
        return 1

    _print(console, f"[bold green]uploaded[/bold green] task_id={task_id}  image_mode={payload.get('image_mode')}")
    if not args.watch:
        print(task_id)
        return 0

    rc = watch_task(console, server, args.token, task_id)
    if rc == 0 and args.out:
        rc = _download_and_extract(console, server, args.token, task_id, args.out)
    return rc


def _download_and_extract(
    console, server: str, token: str | None, task_id: str, out_dir: str
) -> int:
    out_root = Path(out_dir)
    out_root.mkdir(parents=True, exist_ok=True)
    zip_path = out_root / f"{task_id}.zip"
    extract_dir = out_root / task_id

    status, data = ensure_status_terminal(console, server, token, task_id)
    if status != "completed":
        detail = data.get("detail") or data.get("error") or f"task {status}"
        _err(console, f"download aborted: {detail}")
        return 1

    url = f"{server}/api/v1/tasks/{task_id}/download"
    try:
        with requests.get(
            url,
            headers=build_headers(token),
            stream=True,
            timeout=(10.0, None),
        ) as resp:
            if not resp.ok:
                if resp.status_code == 410:
                    _err(console, "task failed; no result zip available")
                else:
                    _err(console, f"download HTTP {resp.status_code}")
                return 1
            total = int(resp.headers.get("Content-Length") or 0)
            with zip_path.open("wb") as fh:
                if console is not None and total > 0:
                    from rich.progress import BarColumn, Progress, TextColumn
                    with Progress(
                        TextColumn("[bold blue]downloading"),
                        BarColumn(bar_width=32),
                        TextColumn("{task.completed}/{task.total} bytes"),
                        console=console,
                    ) as p:
                        task = p.add_task("zip", total=total)
                        for chunk in resp.iter_content(chunk_size=DOWNLOAD_CHUNK):
                            if chunk:
                                fh.write(chunk)
                                p.update(task, advance=len(chunk))
                else:
                    for chunk in resp.iter_content(chunk_size=DOWNLOAD_CHUNK):
                        if chunk:
                            fh.write(chunk)
    except requests.RequestException as e:
        _err(console, f"download error: {e}")
        return 2

    extract_dir.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(extract_dir)
    except zipfile.BadZipFile as e:
        _err(console, f"invalid zip: {e}")
        return 1

    _print(console, f"[bold green]saved[/bold green] {zip_path}")
    _print(console, f"[bold green]extracted[/bold green] {extract_dir}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    console = console_or_none()
    server = args.server.rstrip("/")
    if not args.watch:
        url = f"{server}/api/v1/tasks/{args.task_id}"
        try:
            resp = requests.get(url, headers=build_headers(args.token), timeout=10.0)
        except requests.RequestException as e:
            _err(console, f"status error: {e}")
            return 2
        data = check_resp(resp)
        if data is None:
            return 1
        print_status(console, data)
        return 0

    return watch_with_progress(console, server, args.token, args.task_id)


def cmd_download(args: argparse.Namespace) -> int:
    console = console_or_none()
    server = args.server.rstrip("/")
    return _download_and_extract(console, server, args.token, args.task_id, args.out)


def cmd_delete(args: argparse.Namespace) -> int:
    console = console_or_none()
    server = args.server.rstrip("/")
    url = f"{server}/api/v1/tasks/{args.task_id}"
    try:
        resp = requests.delete(url, headers=build_headers(args.token), timeout=10.0)
    except requests.RequestException as e:
        _err(console, f"delete error: {e}")
        return 2
    if resp.status_code == 204:
        _print(console, f"[bold green]deleted[/bold green] {args.task_id}  HTTP 204")
        return 0
    data = check_resp(resp)
    if data is None:
        return 1
    _print(console, f"HTTP {resp.status_code}: {data}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    def common_auth(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--server",
            default=os.environ.get("OCR_SERVER", DEFAULT_SERVER),
            help="server base URL (default: $OCR_SERVER or http://127.0.0.1:10001)",
        )
        p.add_argument(
            "--token",
            default=os.environ.get("OCR_API_TOKEN"),
            help="bearer token (default: $OCR_API_TOKEN)",
        )

    parser = argparse.ArgumentParser(
        prog="ocr-client",
        description="Unlimited-OCR HTTP client",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_up = sub.add_parser("upload", help="upload a PDF and create an OCR task")
    common_auth(p_up)
    p_up.add_argument("pdf", help="path to PDF file")
    p_up.add_argument(
        "--image-mode",
        choices=("gundam", "base"),
        default="base",
        help="image preprocessing mode (default: base)",
    )
    p_up.add_argument(
        "--concurrency-hint",
        type=int,
        choices=range(1, 17),
        metavar="N",
        default=None,
        help="client-suggested concurrency 1..16",
    )
    p_up.add_argument(
        "--out",
        default="./out",
        help="output directory (default: ./out)",
    )
    p_up.add_argument(
        "--watch",
        action="store_true",
        help="poll status until terminal, then auto-download to --out",
    )
    p_up.set_defaults(func=cmd_upload)

    p_st = sub.add_parser("status", help="fetch task status")
    common_auth(p_st)
    p_st.add_argument("task_id", help="12-char hex task id")
    p_st.add_argument(
        "--watch",
        action="store_true",
        help="poll every 3s and render a progress bar",
    )
    p_st.set_defaults(func=cmd_status)

    p_dl = sub.add_parser("download", help="download and extract task result")
    common_auth(p_dl)
    p_dl.add_argument("task_id", help="12-char hex task id")
    p_dl.add_argument("--out", default="./out", help="output directory (default: ./out)")
    p_dl.set_defaults(func=cmd_download)

    p_de = sub.add_parser("delete", help="delete a task and its result")
    common_auth(p_de)
    p_de.add_argument("task_id", help="12-char hex task id")
    p_de.set_defaults(func=cmd_delete)

    p_hc = sub.add_parser("health", help="GET /api/v1/health")
    common_auth(p_hc)
    p_hc.set_defaults(func=cmd_health)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        console = console_or_none()
        _err(console, "interrupted")
        return 130
    except RuntimeError as e:
        console = console_or_none()
        _err(console, str(e))
        return 1


if __name__ == "__main__":
    sys.exit(main())

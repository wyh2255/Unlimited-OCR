"""Rich-or-print presentation layer for the CLI.

Three subcommand paths exist:
- `cmd_status --watch` uses `_watch_with_rich` (if rich installed) or
  `_watch_with_plain` (ASCII bar fallback).
- `cmd_upload --watch` uses `_watch_task` (no bar; just status transitions).
- `cmd_download` uses `_ensure_status_terminal` (wait for completed/failed).

All paths import `_print`/`_err`/`_console` from this module.
"""
from __future__ import annotations

import sys
import time
from typing import Any

import requests

try:
    from rich.console import Console
    from rich.progress import (
        BarColumn,
        MofNCompleteColumn,
        Progress,
        SpinnerColumn,
        TextColumn,
        TimeElapsedColumn,
    )
    from rich.table import Table
    _RICH_OK = True
except Exception:
    _RICH_OK = False


def console_or_none():
    if _RICH_OK:
        return Console()
    return None


def _print(console, *args, **kwargs):
    if console is not None:
        console.print(*args, **kwargs)
    else:
        if args:
            print(*args, **kwargs)
        elif kwargs:
            print(kwargs)


def _err(console, msg: str) -> None:
    if console is not None:
        console.print(f"[bold red]error:[/bold red] {msg}")
    else:
        print(f"error: {msg}", file=sys.stderr)


def print_status(console, data: dict[str, Any]) -> None:
    if console is None:
        for k, v in data.items():
            print(f"  {k}: {v}")
        return
    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column(style="bold cyan", no_wrap=True)
    table.add_column()
    for k, v in data.items():
        table.add_row(str(k), "" if v is None else str(v))
    console.print(table)


def _ascii_bar(current: int, total: int, width: int = 32) -> str:
    if total <= 0:
        return "-" * width
    filled = int(round(width * current / total))
    filled = max(0, min(width, filled))
    return "#" * filled + "-" * (width - filled)


def watch_task(console, server: str, token: str | None, task_id: str) -> int:
    """Used by `cmd_upload --watch`: poll and print status transitions only (no bar)."""
    from .api import build_headers, check_resp
    url = f"{server}/api/v1/tasks/{task_id}"
    last_status: str | None = None
    while True:
        try:
            resp = requests.get(url, headers=build_headers(token), timeout=10.0)
        except requests.RequestException as e:
            _err(console, f"status poll error: {e}")
            time.sleep(3.0)
            continue
        data = check_resp(resp)
        if data is None:
            return 1
        status = data.get("status")
        if status != last_status:
            _print(console, f"status -> {status}")
            last_status = status
        if status in ("completed", "failed"):
            print_status(console, data)
            if status == "failed":
                _err(console, data.get("error") or "task failed")
                return 1
            return 0
        time.sleep(3.0)


def _watch_with_rich(console, server: str, token: str | None, task_id: str) -> int:
    from .api import fetch_status
    url = f"{server}/api/v1/tasks/{task_id}"
    progress = Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(bar_width=32),
        MofNCompleteColumn(),
        TextColumn("{task.fields[status]}"),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    )
    with progress:
        task_id_progress = progress.add_task(
            f"task {task_id}",
            total=None,
            status="queued",
            current=0,
            total_pages=0,
        )
        while True:
            data = fetch_status(server, token, task_id)
            if data is None:
                _err(console, f"status poll error: failed to fetch {url}")
                return 1
            if "__error__" in data:
                progress.update(task_id_progress, status=f"error: {data['__error__']}")
                time.sleep(3.0)
                continue
            status = data.get("status", "?")
            current = int(data.get("current_page") or 0)
            total = int(data.get("total_pages") or 0)
            progress.update(
                task_id_progress,
                total=(total if total > 0 else None),
                completed=current,
                status=status,
                current=current,
                total_pages=total,
            )
            if status in ("completed", "failed"):
                progress.update(task_id_progress, status=status, completed=total)
                break
            time.sleep(3.0)
    print_status(console, data)
    if status == "failed":
        _err(console, data.get("error") or "task failed")
        return 1
    return 0


def _watch_with_plain(console, server: str, token: str | None, task_id: str) -> int:
    from .api import fetch_status
    last = -1
    last_status: str | None = None
    while True:
        data = fetch_status(server, token, task_id)
        if data is None:
            _err(console, "status poll error")
            return 1
        if "__error__" in data:
            print(f"  poll error: {data['__error__']}", file=sys.stderr)
            time.sleep(3.0)
            continue
        status = data.get("status", "?")
        current = int(data.get("current_page") or 0)
        total = int(data.get("total_pages") or 0)
        if status != last_status or current != last:
            bar = _ascii_bar(current, total)
            print(f"  [{bar}] {current}/{total}  {status}", flush=True)
            last = current
            last_status = status
        if status in ("completed", "failed"):
            print_status(console, data)
            if status == "failed":
                _err(console, data.get("error") or "task failed")
                return 1
            return 0
        time.sleep(3.0)


def watch_with_progress(console, server: str, token: str | None, task_id: str) -> int:
    """Used by `cmd_status --watch`: pick rich or plain based on console availability."""
    if console is not None:
        return _watch_with_rich(console, server, token, task_id)
    return _watch_with_plain(console, server, token, task_id)


def ensure_status_terminal(
    console, server: str, token: str | None, task_id: str
) -> tuple[str, dict[str, Any]]:
    """Wait until status is `completed` or `failed`. Returns (status, data)."""
    from .api import fetch_status
    while True:
        data = fetch_status(server, token, task_id)
        if data is None:
            return ("error", {"detail": "no response"})
        if "__error__" in data:
            return ("error", {"detail": data["__error__"]})
        status = data.get("status", "?")
        if status in ("completed", "failed"):
            return (status, data)
        time.sleep(3.0)

---
日期: 2026-06-26
文档类型: API 协议契约（英文补充）
文档概述: API_CONTRACT.md 的英文精简版，仅覆盖端点形状 + 状态码 + auth
---

# API Wire Protocol (English supplement)

> The canonical (authoritative) contract is [`API_CONTRACT.md`](../API_CONTRACT.md) (中文). This file is an English supplement: endpoint shapes, status codes, and auth only — not a full translation. Where this file disagrees with the 中文 contract, the 中文 one wins.

## 1. Network & ports

| Role | Listen address | Port |
|------|----------------|------|
| FastAPI gateway | `0.0.0.0` | `10001` |
| SGLang inference | `0.0.0.0` | `10000` (started internally by `inference/batch.py`) |

Health check: `GET /api/v1/health` returns 200 with a body containing GPU info. All other endpoints require auth.

## 2. Auth

- Token source: `OCR_API_TOKEN` env var at server startup. If unset, the server generates `secrets.token_urlsafe(24)` and prints it once to stdout.
- Request header: `Authorization: Bearer <token>`
- Missing or wrong token: `401 {"detail": "invalid token"}`
- Token comparison: `secrets.compare_digest` (timing-safe).
- All endpoints except `GET /api/v1/health` require auth.

## 3. Task state machine

```
queued → running → (completed | failed)
```

| Field | Type | Notes |
|-------|------|-------|
| `task_id` | string | 12 hex chars (truncated UUID4) |
| `status` | enum | `queued` / `running` / `completed` / `failed` |
| `progress` | float | 0.0 ~ 1.0 |
| `current_page` | int | Pages completed (only while `running`) |
| `total_pages` | int | Total PDF pages (known up front) |
| `image_mode` | string | `gundam` / `base` (see image-modes-reference.md) |
| `concurrency` | int | Actual concurrency in use (0 while `queued`) |
| `error` | string\|null | Populated on `failed` |
| `created_at` | ISO 8601 string | |
| `started_at` | ISO 8601 string\|null | |
| `finished_at` | ISO 8601 string\|null | |

## 4. Endpoints

### 4.1 `GET /api/v1/health` (no auth)

**Response 200**:
```json
{
  "status": "ok",
  "gpu": {
    "name": "NVIDIA A100",
    "total_mb": 40960,
    "free_mb": 38421,
    "used_mb": 2539
  },
  "concurrency_recommended": 8,
  "queue_length": 0,
  "current_task": "abc123def456" | null
}
```

### 4.2 `POST /api/v1/tasks` (auth)

**Request**: `multipart/form-data`
- `file`: PDF bytes, required, ≤ 200 MB
- `image_mode`: form field, optional, value `gundam` / `base`, default `base`
- `concurrency_hint`: form field, optional, int 1..16

**Response 202**:
```json
{
  "task_id": "abc123def456",
  "status": "queued",
  "image_mode": "base",
  "concurrency_hint": null
}
```

**Errors**:
- `400` — file is not a PDF or exceeds 200 MB
- `401` — auth failed

### 4.3 `GET /api/v1/tasks/{task_id}` (auth)

**Response 200**: see §3 state object

**Errors**:
- `404` — task_id not found
- `401` — auth failed

### 4.4 `GET /api/v1/tasks/{task_id}/download` (auth)

**Response 200**:
- `Content-Type: application/zip`
- `Content-Disposition: attachment; filename="<task_id>.zip"`
- Body is a ZIP stream

**ZIP structure**:
```
<task_id>.zip
├── result.md
└── images/
    ├── page_0001_0.jpg
    ├── page_0001_1.jpg
    └── ...
```

**Errors**:
- `404` — task not found OR not yet completed
- `410` — task has `failed`; no zip available
- `401` — auth failed

### 4.5 `DELETE /api/v1/tasks/{task_id}` (auth)

Cleans the zip + removes the task from in-memory state. If the task is `queued`, it is removed from the queue (will not be processed). If `running`, the worker continues; the resulting zip becomes an orphan.

**Response 204** (no body).

**Errors**:
- `404` — task_id not found
- `401` — auth failed

## 5. Unified error response

```json
{"detail": "human readable message"}
```

Status codes used: `400` / `401` / `404` / `410` / `500`.

> Note: the 中文 contract also lists `413` and `503`. `413` is **not** actually returned by the server (the 200 MB cap is enforced in-process and returns `400`); `503` is **not** actually returned (the design uses a FIFO queue, so a second upload is queued, not rejected).

## 6. CORS

The server installs `fastapi.middleware.cors.CORSMiddleware` and exposes a `--cors-origin` CLI flag (repeatable, default `["*"]` for LAN). `expose_headers=["Content-Disposition"]` so the browser JS can read the suggested ZIP filename. The middleware is installed via a `configure_cors(origins)` helper that wipes any previous CORS entries from `app.user_middleware` first (FastAPI's middleware stack cannot be added to an already-running app the normal way).

## 7. GPU auto-tiering

`detect_concurrency(gpu_index: int = 0) -> int` shells out to `nvidia-smi --query-gpu=memory.free`:

| Free GPU memory | Concurrency |
|-----------------|-------------|
| `>= 30 GB`      | `8`         |
| `>= 10 GB`      | `4`         |
| `< 10 GB`       | `2`         |

User override per task via `concurrency_hint` (1..16). The detected value lives in `GET /api/v1/health → concurrency_recommended`.

## 8. Directory layout on the server host

```
./api_workdir/
├── tmp/<task_id>/             # per-task scratch; removed on completion
├── outputs/<task_id>.zip      # final result; kept until DELETE
└── logs/<task_id>_sglang.log  # per-task SGLang log; kept until DELETE
```

The `--workdir` flag controls the parent directory (default `./api_workdir`).

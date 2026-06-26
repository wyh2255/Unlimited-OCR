---
日期: 2026-06-26
文档类型: API 协议契约
文档概述: Unlimited-OCR 局域网服务的客户端-服务端接口规范，作为 server.py、client.py、文档等多个 subagent 的协同基准
---

# API 协议契约 v1.0

> 所有实现者必须严格遵守本文档。冲突时以本文档为准。

## 1. 网络与端口

| 角色 | 监听地址 | 端口 |
|---|---|---|
| FastAPI 网关 | `0.0.0.0` | `10001` |
| SGLang 推理 | `0.0.0.0` | `10000`（由 `infer.py` 内部启动） |

健康检查：`GET /api/v1/health` 返回 200，body 含 GPU 信息。其他接口需要鉴权。

## 2. 鉴权

- 启动时从环境变量 `OCR_API_TOKEN` 读取；未设置则生成 `secrets.token_urlsafe(24)` 并打印到 stdout 一次
- 请求头：`Authorization: Bearer <token>`
- 缺失或错误：返回 `401 {"detail": "invalid token"}`

## 3. 任务状态机

```
queued → running → (completed | failed)
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `task_id` | string | 12 位 hex（UUID4 截断） |
| `status` | enum | `queued`/`running`/`completed`/`failed` |
| `progress` | float | 0.0 ~ 1.0 |
| `current_page` | int | 已完成页数（仅 running） |
| `total_pages` | int | PDF 总页数（running 时即可知） |
| `image_mode` | string | `gundam` / `base` |
| `concurrency` | int | 实际使用的并发数 |
| `error` | string\|null | 失败时填写 |
| `created_at` | ISO 8601 string | |
| `started_at` | ISO 8601 string\|null | |
| `finished_at` | ISO 8601 string\|null | |

## 4. 接口

### 4.1 `GET /api/v1/health`（免鉴权）

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

### 4.2 `POST /api/v1/tasks`（鉴权）

**Request**: `multipart/form-data`
- `file`: PDF 字节流，必填，≤ 200 MB
- `image_mode`: form 字段，可选，值 `gundam` / `base`，默认 `base`
- `concurrency_hint`: form 字段，可选，int 1~16

**Response 202**:
```json
{
  "task_id": "abc123def456",
  "status": "queued",
  "image_mode": "base",
  "concurrency_hint": null
}
```

**错误**：
- `400` 文件不是 PDF / 超过 200 MB
- `401` 鉴权失败
- `503` 当前已有 running 任务（仅当 worker 模式严格串行；本方案允许排队，所以不会返回 503）

### 4.3 `GET /api/v1/tasks/{task_id}`（鉴权）

**Response 200**: 见 §3 状态对象

**错误**：
- `404` task_id 不存在
- `401` 鉴权失败

### 4.4 `GET /api/v1/tasks/{task_id}/download`（鉴权）

**Response 200**:
- `Content-Type: application/zip`
- `Content-Disposition: attachment; filename="<task_id>.zip"`
- body 为 ZIP 流

**ZIP 内部结构**：
```
<task_id>.zip
├── result.md
└── images/
    ├── page_0001_0.jpg
    ├── page_0001_1.jpg
    └── ...
```

**错误**：
- `404` task 不存在 / 未完成
- `410` task 已 failed，zip 不存在

### 4.5 `DELETE /api/v1/tasks/{task_id}`（鉴权）

清理 zip + 取消（若 queued）。Response 204。

## 5. 错误响应统一格式

```json
{"detail": "human readable message"}
```

状态码：400 / 401 / 404 / 410 / 413 / 500 / 503。

## 6. 文件与目录布局

```
Unlimited-OCR/
├── server.py              # 新建
├── client.py              # 新建
├── infer.py               # 改动：新增 run_inference() 函数，main() 不变
├── postprocess_sglang.py  # 不动
└── requirements-api.txt   # 新建
```

**server 进程内目录**：
```
./api_workdir/
├── tmp/<task_id>/         # 中间产物（任务完成后清理）
└── outputs/<task_id>.zip  # 最终结果（保留到被 DELETE 或过期）
```

## 7. GPU 内存检测 + 三档降级

**`detect_concurrency()` 函数签名**（必须存在于 `server.py`）：

```python
def detect_concurrency(gpu_index: int = 0) -> int:
    """Return 8 / 4 / 2 based on free GPU memory."""
```

调用 `nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits -i <idx>`。

| free GB | concurrency |
|---|---|
| `>= 30` | `8` |
| `>= 10` | `4` |
| `< 10`  | `2` |

## 8. infer.py 必须新增的函数

```python
def run_inference(
    *,
    pdf: str,
    output_dir: str,
    concurrency: int,
    model_dir: str,
    gpu: str,
    image_mode: str,
    server_log: str,
) -> dict:
    """Run end-to-end inference on a PDF.
    
    Starts SGLang server, fans out concurrent requests, stops server.
    Returns dict with keys: output_dir, request_count, successful, total_tokens, wall_time.
    """
```

`main()` 入口**必须**保持原样（CLI 行为完全兼容）。

## 9. 调用关系

```
client.py  ──HTTP──►  server.py
                       │
                       ▼ worker thread
                       run_inference() ──► infer.py 内部 SGLang server
                       postprocess()    ──► postprocess_sglang.py
                       zip + cleanup
```

## 10. 依赖新增

`requirements-api.txt`：
```
fastapi>=0.110
uvicorn[standard]>=0.27
python-multipart>=0.0.9
rich>=13.7
requests>=2.31
pymupdf>=1.24
Pillow>=10.0
```

注意：`torch`、`sglang`（本地 wheel）、`kernels` 不在此列，沿用现有 venv。

## 11. 端到端验收

启动 server 后 `curl` 必须能跑通：
1. `curl http://127.0.0.1:10001/api/v1/health` → 200 + GPU 信息
2. 无 token 访问 `/api/v1/tasks` 任何端点 → 401
3. `client.py upload some.pdf` → task_id
4. `client.py status <id>` → 进度增长，最终 completed
5. `client.py download <id>` → 解压后有 `result.md` 和 `images/`

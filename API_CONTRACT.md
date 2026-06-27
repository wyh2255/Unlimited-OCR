---
日期: 2026-06-27
文档类型: API 协议契约
文档概述: Unlimited-OCR 局域网服务的客户端-服务端接口规范，作为 gateway/server.py、clients/python-cli/、文档等多个 subagent 的协同基准
---

# API 协议契约 v1.1

> 所有实现者必须严格遵守本文档。冲突时以本文档为准。

## 1. 网络与端口

| 角色 | 监听地址 | 端口 |
|---|---|---|
| FastAPI 网关 | `0.0.0.0` | `10001` |
| SGLang 推理 | `0.0.0.0` | `10000`（由 `inference/batch.py` 内部启动） |

支持 `--peers` CLI 参数配置对等节点，实现双 GPU 自动调度（见 §12）。

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

**Response 200** — 当未配置 `--peers` 时，返回格式与 v1.0 一致。

当配置了 `--peers` 时，新增 `self` / `peers` / `best_target` 字段，旧字段 `gpu` / `concurrency_recommended` / `queue_length` / `current_task` 仍然保留（向后兼容，值为 `self` 对应值）。

```json
{
  "status": "ok",

  "self": {
    "name": "NVIDIA A100",
    "gpu": { "name": "NVIDIA A100", "total_mb": 40960, "free_mb": 38421, "used_mb": 2539 },
    "concurrency_recommended": 8,
    "queue_length": 0,
    "current_task": "abc123def456" | null,
    "free_mb": 38421
  },

  "peers": {
    "http://192.168.1.100:10001": {
      "online": true,
      "name": "NVIDIA GeForce RTX 3090",
      "gpu": { "name": "NVIDIA GeForce RTX 3090", "total_mb": 24576, "free_mb": 18432, "used_mb": 6144 },
      "concurrency_recommended": 4,
      "queue_length": 0,
      "current_task": null
    }
  },

  "best_target": "self",

  "gpu": { "name": "NVIDIA A100", "total_mb": 40960, "free_mb": 38421, "used_mb": 2539 },
  "concurrency_recommended": 8,
  "queue_length": 0,
  "current_task": "abc123def456" | null
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `self` | object | 本节点健康的完整信息（同上）|
| `peers` | object | 对等节点 URL → 健康对象 的映射，key 为 `--peers` 中的 URL |
| `peers.{url}.online` | bool | 是否 probe 成功（超时/拒绝则为 false）|
| `peers.{url}.name` | string | GPU 名称 |
| `peers.{url}.gpu` | object | GPU 显存信息 |
| `peers.{url}.concurrency_recommended` | int | 推荐并发数 |
| `peers.{url}.queue_length` | int | 队列长度 |
| `peers.{url}.current_task` | string\|null | 正在运行的任务 id |
| `best_target` | string | `"self"` 或对等节点 URL，由调度算法选出的最优节点 |

**v1.0 客户端兼容**：不读取 `self`/`peers`/`best_target` 的旧客户端仍然可以读 `gpu` / `concurrency_recommended` / `queue_length` / `current_task` 正常使用。

### 4.2 `POST /api/v1/tasks`（鉴权）

**Request**: `multipart/form-data`
- `file`: PDF 字节流，必填，≤ 200 MB
- `image_mode`: form 字段，可选，值 `gundam` / `base`，默认 `base`
- `concurrency_hint`: form 字段，可选，int 1~16

**Response 202** — 本地处理时：

```json
{
  "task_id": "abc123def456",
  "status": "queued",
  "image_mode": "base",
  "concurrency_hint": null
}
```

**Response 202** — 转发到对等节点时（多出 `backend` 字段）：

```json
{
  "task_id": "abc123def456",
  "status": "queued",
  "image_mode": "base",
  "concurrency_hint": null,
  "backend": "http://192.168.1.100:10001"
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `backend` | string | 可选。实际处理该任务的节点 URL。仅当任务被调度到对等节点时出现。 |

**错误**：
- `400` 文件不是 PDF / 超过 200 MB
- `401` 鉴权失败
- `502` 转发到对等节点时失败（对等节点返回错误或不可达）
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
├── gateway/server.py              # FastAPI 网关
├── gateway/peers.py               # 对等调度（PeerConfig、探测、选路、代理）
├── gateway/state.py               # 运行时状态（含 peers / proxied 映射）
├── gateway/concurrency.py         # GPU 并发检测（支持 OCR_CONCURRENCY_TIERS 覆盖）
├── clients/python-cli/            # CLI 客户端
├── inference/cli.py + batch.py    # SGLang 批处理
├── inference/postprocess.py       # 后处理
└── requirements-api.txt   # 新建
```

**server 进程内目录**：
```
./api_workdir/
├── tmp/<task_id>/         # 中间产物（任务完成后清理）
└── outputs/<task_id>.zip  # 最终结果（保留到被 DELETE 或过期）
```

## 7. GPU 内存检测 + 三档降级

**`detect_concurrency()` 函数签名**（存在于 `gateway/concurrency.py`）：

```python
def detect_concurrency(gpu_index: int = 0) -> int:
    """Return 8 / 4 / 2 based on free GPU memory."""
```

调用 `nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits -i <idx>`。

| free GB | concurrency (A100 默认) | concurrency (3090 建议值) |
|---|---|---|
| `>= 30` | `8` | — |
| `>= 16` | — | `4` |
| `>= 10` | `4` | — |
| `>= 6`  | — | `2` |
| `< 10`  | `2` | — |
| `< 6`   | — | `1` |

可通过环境变量 `OCR_CONCURRENCY_TIERS` 覆盖，格式：`"threshold_gb:concurrency,threshold_gb:concurrency,..."`。

示例：`OCR_CONCURRENCY_TIERS="16:4,6:2,0:1"` 表示空闲 ≥16GB 时并发 4，≥6GB 时并发 2，否则并发 1。

## 8. inference/batch.py 的函数

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
    ```


## 9. 调用关系

```
ocr-client  ──HTTP──►  gateway/server.py
                        │
                        ▼ worker thread
                        run_inference() ──► SGLang server (:10000)
                        inference.postprocess()
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
3. `ocr-client upload some.pdf` → task_id
4. `ocr-client status <id>` → 进度增长，最终 completed
5. `ocr-client download <id>` → 解压后有 `result.md` 和 `images/`

## 12. 对等调度 (Peer Dispatch) v1.1

### 12.1 概述

通过 `--peers` CLI 参数将多台网关组成对等集群。每台机器运行完全相同的 `gateway/server.py`，通过 HTTP 互探健康、自动调度。

### 12.2 CLI 配置

```bash
python -m gateway.server \
    --port 10001 \
    --peers "http://192.168.1.100:10001,<peer-token>"
```

- `--peers` 可重复传递，每台机器配置一个
- 格式：`url,token`
- 未配置 `--peers` 时表现为传统单机模式（完全向后兼容）

### 12.3 调度逻辑

```
上传 POST /api/v1/tasks
  → probe 所有 peers 的 /health（超时 3s）
  → 合并自身 + peers 的健康信息
  → select_best_backend() 选出最优节点:
    1. 空闲（无运行中任务）优先
    2. 队列最短优先
    3. 空闲显存最大优先
    4. 同分时优先选择自身（self）
  → 如果最优节点是 peer:
    → multipart 转发 PDF 到 peer 的 /api/v1/tasks
    → 返回 peer 的 {task_id, backend: peer_url} 给客户端
  → 如果最优节点是自身:
    → 本地处理（原有逻辑不变）
```

### 12.4 代理请求

对于转发到对等节点的任务，状态查询、下载、删除请求自动代理到对应节点：

| 客户端请求 | 代理行为 |
|---|---|
| `GET /api/v1/tasks/{id}` | 转发到 peer，返回 peer 的响应 |
| `GET /api/v1/tasks/{id}/download` | 转发到 peer，流式返回 ZIP 字节 |
| `DELETE /api/v1/tasks/{id}` | 转发到 peer 删除，清理本地 proxied 映射 |

### 12.5 单机降级

- 所有 peers probe 超时时自动选 `self`（自身处理）
- 未设置 `--peers` 时完全退化为 v1.0 单机行为

### 12.6 并发阈值覆盖

通过环境变量 `OCR_CONCURRENCY_TIERS` 调整每台机器的并发策略：
```bash
# 3090 建议配置（24GB）
export OCR_CONCURRENCY_TIERS="16:4,6:2,0:1"

# A100 默认（40GB）— 不设置环境变量即用内置默认值
# 内置默认: ≥30GB→8, ≥10GB→4, 否则→2
```

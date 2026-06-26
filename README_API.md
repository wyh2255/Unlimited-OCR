---
日期: 2026-06-26
文档类型: 用户使用手册
文档概述: 局域网 PDF OCR 服务（server.py + client.py）的快速上手、配置、API 参考
---

# Unlimited-OCR 局域网 API 服务使用手册

## 1. 简介

本服务把 Unlimited-OCR 推理能力封装成局域网 HTTP API。局域网内任意笔记本可以把 PDF 上传到一台带 GPU 的服务器做 OCR,完成后下载结构化的 `result.md` 和原始图片 ZIP。

## 2. 架构

```
┌────────────┐    HTTP    ┌──────────────────────┐    HTTP    ┌─────────────────────┐
│  client.py │ ─────────► │   server.py (网关)   │ ─────────► │ infer.py 内置 SGLang │
│ (笔记本)   │  :10001    │   FastAPI + worker   │  :10000    │ OpenAI 兼容端点     │
└────────────┘            └──────────────────────┘            └─────────────────────┘
                                  │
                                  │ 任务完成后
                                  ▼
                          ./api_workdir/
                          ├── tmp/<task_id>/     # 中间产物
                          └── outputs/<task_id>.zip
```

- 客户端只连 `:10001`(FastAPI 网关)。
- `:10000` 是 SGLang 推理服务,由 `infer.py` 在 worker 线程内按需拉起,**不需要**手动启动。
- 上传 → 入队 → 后台 worker 拉起 SGLang → 并发 OCR → 后处理 → 打包成 ZIP → 客户端下载。

## 3. 服务器部署

### 3.1 安装依赖

```bash
uv pip install -r requirements-api.txt
```

> `torch`、`sglang`(本地 wheel)、`kernels`、`pymupdf`、`Pillow` 已装在别的位置,不在本文件里。

### 3.2 启动

```bash
export OCR_API_TOKEN="<自定义长随机串>"   # 可选,不设就自动生成
python server.py --host 0.0.0.0 --port 10001
```

- 未设置 `OCR_API_TOKEN` 时,server 启动时用 `secrets.token_urlsafe(24)` 生成一个随机 token 并打印到 stdout 一次,请立刻抄走。
- token 校验走 `Authorization: Bearer <token>` 头,缺失或错误统一返回 `401 {"detail": "invalid token"}`。

## 4. 客户端使用

### 4.1 上传 PDF

```bash
python client.py upload doc.pdf \
    --server http://x.x.x.x:10001 \
    --token xxx \
    --watch
```

- `--watch`:进入循环轮询,任务完成后自动下载并退出。
- 不加 `--watch`:只打印 `task_id` 就退出,后续手动查状态 / 下载。
- 可选 `--image-mode gundam|base`(默认 `base`)和 `--concurrency-hint 1..16`。

### 4.2 其它子命令

| 子命令 | 用途 |
|---|---|
| `python client.py status <task_id> --server ... --token ...` | 查询任务状态与进度 |
| `python client.py download <task_id> --out ./out --server ... --token ...` | 下载结果 ZIP |
| `python client.py delete <task_id> --server ... --token ...` | 清理 ZIP + 取消排队中的任务 |
| `python client.py health --server ...` | 健康检查(免 token) |

## 5. API 参考

基础路径:`/api/v1`。除 `health` 外,所有接口都需要 `Authorization: Bearer <token>`。

### 5.1 `GET /api/v1/health`(免鉴权)

查看 GPU 状态、推荐并发、当前队列长度。

**curl**:
```bash
curl http://127.0.0.1:10001/api/v1/health
```

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
  "current_task": "abc123def456"
}
```

### 5.2 `POST /api/v1/tasks`(鉴权)

上传 PDF,创建 OCR 任务,返回 `task_id`。

**curl**:
```bash
curl -X POST http://127.0.0.1:10001/api/v1/tasks \
    -H "Authorization: Bearer $TOKEN" \
    -F "file=@doc.pdf" \
    -F "image_mode=base" \
    -F "concurrency_hint=8"
```

| 字段 | 必填 | 说明 |
|---|---|---|
| `file` | 是 | PDF 字节流,≤ 200 MB |
| `image_mode` | 否 | `gundam` / `base`,默认 `base` |
| `concurrency_hint` | 否 | 整数 1~16,不传则用自动降级值 |

**Response 202**:`{"task_id": "abc123def456", "status": "queued", ...}`

**错误**:`400` 不是 PDF 或超 200 MB / `401` 鉴权失败。

### 5.3 `GET /api/v1/tasks/{task_id}`(鉴权)

查询任务状态、进度、已用 / 总页数。

**curl**:
```bash
curl -H "Authorization: Bearer $TOKEN" \
    http://127.0.0.1:10001/api/v1/tasks/abc123def456
```

**Response 200**(关键字段):

| 字段 | 类型 | 说明 |
|---|---|---|
| `status` | enum | `queued` / `running` / `completed` / `failed` |
| `progress` | float | 0.0 ~ 1.0 |
| `current_page` | int | 已完成页数 |
| `total_pages` | int | PDF 总页数 |
| `image_mode` | string | `gundam` / `base` |
| `concurrency` | int | 实际使用的并发数 |
| `error` | string\|null | 失败原因 |

**错误**:`404` task_id 不存在 / `401` 鉴权失败。

### 5.4 `GET /api/v1/tasks/{task_id}/download`(鉴权)

下载结果 ZIP。

**curl**:
```bash
curl -OJ -H "Authorization: Bearer $TOKEN" \
    http://127.0.0.1:10001/api/v1/tasks/abc123def456/download
```

**Response 200**:`Content-Type: application/zip`,`Content-Disposition: attachment; filename="<task_id>.zip"`。

**ZIP 结构**:
```
<task_id>.zip
├── result.md
└── images/
    ├── page_0001_0.jpg
    ├── page_0001_1.jpg
    └── ...
```

**错误**:`404` 任务不存在或还没完成 / `410` 任务已 failed。

### 5.5 `DELETE /api/v1/tasks/{task_id}`(鉴权)

清理 ZIP;若任务还在 `queued` 状态,一并取消。**Response 204**。

**curl**:
```bash
curl -X DELETE -H "Authorization: Bearer $TOKEN" \
    http://127.0.0.1:10001/api/v1/tasks/abc123def456
```

### 5.6 统一错误格式

```json
{"detail": "human readable message"}
```

可能的状态码:`400` / `401` / `404` / `410` / `500`。

## 6. GPU 内存自动降级

`server.py` 在 worker 启动时调用 `detect_concurrency(gpu_index=0)`,通过 `nvidia-smi` 查询空闲显存,按三档自动选并发数:

| 空闲显存 | 推荐并发 |
|---|---|
| `>= 30 GB` | `8` |
| `10 ~ 30 GB` | `4` |
| `< 10 GB` | `2` |

如果想覆盖默认值,在上传时传 `concurrency_hint` 即可。

## 7. 文件与目录

服务器进程内,在当前工作目录下创建:

| 路径 | 用途 | 生命周期 |
|---|---|---|
| `./api_workdir/tmp/<task_id>/` | 渲染好的 PDF 图片、并发请求中间产物 | 任务完成后清理 |
| `./api_workdir/outputs/<task_id>.zip` | 最终结果包(含 `result.md` 和 `images/`) | 保留到 `DELETE` 或过期 |

## 8. 常见问题

**Q1. 上传后 `status` 一直是 `queued` 很久不动。**
SGLang 冷启动通常要 30~60 秒加载模型权重。等一两分钟再看 `status` 应当跳到 `running`。

**Q2. 显存不够怎么办。**
访问 `GET /api/v1/health`,看 `concurrency_recommended` 字段,按推荐值上传时再传 `concurrency_hint` 主动压低并发;或换张卡。

**Q3. `401 invalid token`。**
确认客户端 `--token` 和服务器 `OCR_API_TOKEN` 一致;未设置环境变量时检查 server 启动日志里打印出来的自动生成 token。

**Q4. `POST /api/v1/tasks` 报 `400`。**
文件不是 PDF,或超过 200 MB。前端可以预校验大小。

**Q5. `download` 报 `404`。**
任务还在 `running`,没生成 zip。等 `status == completed` 再下载。

**Q6. `download` 报 `410`。**
任务 `failed`,zip 已被清理,看 `status.error` 字段定位原因。

## 9. 安全提示

- 整个服务走**明文 HTTP + Bearer token**,**只适合局域网**。
- 不要把 `:10001` 暴露到公网;不要把 `OCR_API_TOKEN` 提交进 git、贴到群聊。
- 真要跨网段使用,请自己加一层反向代理(Traefik / Caddy)并上 TLS。

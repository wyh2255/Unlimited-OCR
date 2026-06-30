---
日期: 2026-06-30
文档类型: 技术方案
文档概述: Unlimited-OCR 文档转换（PDF→MD→任意格式）与小团队多用户支持实现方案。Phase A 集成 pandoc + weasyprint 实现 5 种格式输出，Phase B 加配置文件多 token + sqlite 轻量持久化 + 任务列表端点 + owner 隔离。Phase C 知识库导出 hook 暂不做。
---

# 文档转换 + 小团队多用户 实现方案

## 目录

- [背景与目标](#背景与目标)
- [核心决策摘要](#核心决策摘要)
- [整体架构](#整体架构)
- [文件变更清单](#文件变更清单)
- [Phase A: 文档转换核心（pandoc + weasyprint）](#phase-a-文档转换核心pandoc--weasyprint)
  - [A.1 后端转换层](#a1-后端转换层)
  - [A.2 下载端点改造](#a2-下载端点改造)
  - [A.3 前端下载菜单](#a3-前端下载菜单)
  - [A.4 CLI 下载格式参数](#a4-cli-下载格式参数)
  - [A.5 契约与文档](#a5-契约与文档)
  - [A.6 依赖与部署](#a6-依赖与部署)
  - [A.7 验收](#a7-验收)
- [Phase B: 小团队多用户 + 持久化](#phase-b-小团队多用户--持久化)
  - [B.1 用户注册表（配置文件）](#b1-用户注册表配置文件)
  - [B.2 鉴权改造](#b2-鉴权改造)
  - [B.3 任务状态扩展 owner](#b3-任务状态扩展-owner)
  - [B.4 列表端点与 /me 端点](#b4-列表端点与-me-端点)
  - [B.5 sqlite 轻量持久化](#b5-sqlite-轻量持久化)
  - [B.6 前端多用户界面](#b6-前端多用户界面)
  - [B.7 CLI 多用户命令](#b7-cli-多用户命令)
  - [B.8 契约与文档](#b8-契约与文档)
  - [B.9 验收](#b9-验收)
- [Phase C: 知识库导出 hook](#phase-c-知识库导出-hook)
- [执行顺序与依赖](#执行顺序与依赖)
- [决策记录](#决策记录)
- [风险与回避](#风险与回避)
- [附录: 接口契约草案](#附录-接口契约草案)

---

## 背景与目标

### 项目现状

当前 Unlimited-OCR 已经是一条完整的 **PDF → MD → ZIP → 客户端** 链路：

- `gateway/server.py` 提供 HTTP API（:10001），接收 PDF，跑 SGLang OCR，后处理输出 `result.md` + `images/`，打包成 ZIP 供下载
- 两条客户端：`clients/python-cli/`（CLI）和 `clients/web/`（Vue 3 SPA）
- 已支持 peer dispatch（多 GPU 节点调度）、GPU 自动分级、Bearer token 鉴权

**输出格式单一**：客户端拿到的永远是 ZIP 包里的 `result.md` + `images/`，用户要 docx/pdf/html 还得自己用工具转。

**单用户假设**：当前只有一个 `OCR_API_TOKEN`，所有任务没有 owner 字段，任务状态纯内存（重启即丢）。

### 用户设定

本项目目的有两层：

1. **文档转换**：PDF / 图片 → MD（中介）→ 任意格式文档 → 交付给人
2. **知识库**：MD 文档作为个人/小团队知识库（暂不做 RAG，方向未定）

配套需求：

- **算力调度**：已有 peer dispatch，多机协同已覆盖，先不扩展
- **人机交互**：当前 web 前端已覆盖上传/进度/预览，需补格式转换下载

### 本次目标

针对 2-10 人小团队场景，本次方案解决两个核心问题：

1. **文档转换**：在现有下载链路上加 pandoc 转换，用户可下载 `md / docx / html / pdf / latex` 五种格式，**转换在服务端完成**，用户无需本地装工具
2. **小团队多用户**：
   - 配置文件式多 token，每个 token 映射一个 owner（用户名）
   - 任务归属到 owner，可"只看我的/看全部"
   - sqlite 轻量持久化，重启不丢任务列表
   - 新增任务列表端点（当前缺失）

知识库导出 hook **暂不做**，等后续方向定了再补。

---

## 核心决策摘要

| 决策点 | 选择 | 理由 |
|--------|------|------|
| MD 作为文档中介 | 是 | OCR 已输出 MD，pandoc 一行转任意格式，零重构成本 |
| 转换执行位置 | 服务端 | 服务化意义所在，用户无需本地装 pandoc |
| 转换工具 | pandoc | MD 转换事实标准，覆盖 docx/html/latex/pdf |
| PDF 引擎 | weasyprint | pip 装，~100MB，HTML 路线，适合轻量部署；xelatex 太重 |
| 暴露格式 | md/docx/html/pdf/latex | 用户勾选的全部 5 种 |
| 默认格式 | md（向后兼容） | 现有客户端不破坏 |
| 用户规模 | 2-10 人小团队 | 不需完整登录系统，多 token + owner 即可 |
| Token 配置方式 | 配置文件（~/.ocr_tokens.json） | 热加载，2-10 人够用，比 env 易管理 |
| 任务持久化 | sqlite（stdlib） | 轻量，无新依赖，重启可恢复列表 |
| 列表可见性 | mine/all 两档 | 小团队信任模型，不做细粒度权限 |
| 知识库 hook | 不做 | 方向未定，等后续 |
| 执行顺序 | A → B → C | 文档转换最核心，先能用；多用户等真有人了再加 |

---

## 整体架构

### 现状架构（改造前）

```
┌─────────────┐    HTTP+Bearer     ┌──────────────────────────┐
│  前端 / CLI  │ ──────────────────►│  gateway/server.py :10001 │
│  单 token    │                    │  内存 STATE.tasks         │
│  下载 ZIP    │ ◄──────────────────│  FIFO worker              │
└─────────────┘   ZIP(result.md)    │  ↓                        │
                                    │  SGLang :10000            │
                                    │  ↓                        │
                                    │  postprocess → zip        │
                                    └──────────────────────────┘
```

### 目标架构（改造后）

```
┌─────────────────────┐  HTTP+Bearer(多 token)  ┌──────────────────────────────────────┐
│  前端 / CLI          │ ───────────────────────►│  gateway/server.py :10001             │
│  显示当前用户         │                         │  ├─ users.py (UserRegistry)           │
│  下载格式下拉         │                         │  │   └─ 读 ~/.ocr_tokens.json         │
│  mine/all 切换       │                         │  ├─ auth.py (get_token→owner)         │
│  list 命令           │                         │  ├─ convert.py (pandoc 封装) ★新      │
└─────────────────────┘                         │  ├─ persist.py (sqlite) ★新           │
        │                                        │  ├─ STATE.tasks[owner]                │
        │  download?format=docx|pdf|html|latex   │  └─ FIFO worker                       │
        │  GET /tasks?scope=mine|all              │     ↓                                 │
        │  GET /me                                │     SGLang → postprocess → zip        │
        │  GET /tasks/{id} (带 owner)             │     ↓                                 │
        │                                        │     convert.py → {id}.docx/pdf/...    │
        │                                        │     ↓                                 │
        │  ZIP / DOCX / PDF / HTML / LATEX        │     sqlite 记录 (task_id, owner, ...) │
        └────────────────────────────────────────┘
```

### 数据流（Phase A 转换路径）

```
客户端 GET /api/v1/tasks/{id}/download?format=docx
  ↓
gateway/server.py download_task()
  ├─ format == "md" → 直接返回 {id}.zip（原逻辑）
  └─ format != "md" →
       ├─ 检查 api_workdir/outputs/{id}.{ext} 缓存
       │   └─ 命中 → FileResponse
       └─ 未命中 →
            ├─ 解 {id}.zip 到 tmp/{id}_convert/
            ├─ convert.convert_result(tmp_dir, fmt, out_path, pdf_engine)
            │   └─ subprocess: pandoc result.md -o out.docx --resource-path .
            ├─ 缓存到 api_workdir/outputs/{id}.docx
            ├─ 清理 tmp/{id}_convert/
            └─ FileResponse(out_path, filename="{id}.docx")
  ↓
DELETE /tasks/{id} 时一并清 {id}.zip / {id}.{ext} / tmp / log / sqlite 行
```

### 数据流（Phase B 持久化）

```
任务状态变更点（tasks.py worker 内）:
  queued → running → (completed | failed)
  ↓ 每次
persist.save_task(task)  # INSERT OR REPLACE
  ↓
api_workdir/tasks.db (sqlite)

启动时 main():
  ↓
persist.load_all() → 重建 STATE.tasks
  ↓ 仍为 running 的标 failed (error="server restarted")
STATE.tasks 重建完成
  ↓
worker_loop 启动
```

---

## 文件变更清单

### Phase A 改动

| 文件 | 类型 | 改动 |
|------|------|------|
| `gateway/convert.py` | **新建** | pandoc 封装：`convert_result()`、格式校验、PDF 引擎选择 |
| `gateway/server.py` | 改 | 下载端点加 `?format=`；`--pandoc-pdf-engine` CLI；DELETE 清转换缓存 |
| `gateway/state.py` | 改 | `STATE` 加 `pandoc_pdf_engine` 字段 |
| `clients/web/src/components/ResultViewer.vue` | 改 | "下载 ZIP" → 下拉菜单 5 格式 |
| `clients/web/src/composables/useApi.ts` | 改 | 加 `downloadAs(taskId, fmt)` |
| `clients/web/src/types/api.ts` | 改 | 加 `DownloadFormat` 类型 |
| `clients/python-cli/src/ocr_client/cli.py` | 改 | `download --format md\|docx\|html\|pdf\|latex` |
| `clients/python-cli/src/ocr_client/api.py` | 改 | 下载请求带 `?format=`，处理单文件响应 |
| `API_CONTRACT.md` | 改 | §4.4 加 `?format=`、各格式 Content-Type、缓存语义 |
| `README_API.md` | 改 | 加 pandoc/weasyprint 安装说明 |
| `Dockerfile` | 改 | `apt install pandoc libpango-1.0-0 libpangoft2-1.0-0` |
| `requirements-api.txt` | 改 | 加 `weasyprint>=60` |
| `docs/project_notes/decisions.md` | 改 | ADR: weasyprint 选型 |

### Phase B 改动

| 文件 | 类型 | 改动 |
|------|------|------|
| `gateway/users.py` | **新建** | `UserRegistry` 类：读 json、热加载、token→owner 映射 |
| `gateway/persist.py` | **新建** | sqlite 封装：`save_task` / `load_all` / `delete_task` |
| `gateway/auth.py` | 改 | `get_token` 返回 owner；接 `UserRegistry` |
| `gateway/state.py` | 改 | `TaskState` 加 `owner`；`_State` 加 `users`；`_task_to_dict` 输出 owner |
| `gateway/server.py` | 改 | `create_task` 写 owner；新增 `GET /tasks` `GET /me`；启动加载持久化；`--tokens-file` CLI |
| `gateway/tasks.py` | 改 | 状态变更调 `persist.save_task`；DELETE 调 `persist.delete_task` |
| `clients/web/src/components/SettingsBar.vue` | 改 | 调 `/me`，显示当前用户 |
| `clients/web/src/components/TaskCard.vue` | 改 | 加 owner 徽章 |
| `clients/web/src/components/TaskList.vue` | 改 | "只看我的/看全部"切换；"从服务端刷新"按钮 |
| `clients/web/src/composables/useApi.ts` | 改 | 加 `listTasks(scope)` `whoami()` |
| `clients/web/src/types/api.ts` | 改 | 加 `owner` 字段、`TaskListResponse` |
| `clients/python-cli/src/ocr_client/cli.py` | 改 | 新增 `list` `whoami` 子命令 |
| `clients/python-cli/src/ocr_client/api.py` | 改 | 加 `listTasks` `whoami` 请求函数 |
| `API_CONTRACT.md` | 改 | §2 多 token；§3 owner；新增 §4.6 列表、§4.7 `/me` |
| `README_API.md` | 改 | tokens.json 格式、多用户使用说明 |
| `docs/project_notes/decisions.md` | 改 | ADR: 配置文件选型、sqlite 选型 |
| `docs/project_notes/key_facts.md` | 改 | 加 `tasks.db` 路径、tokens.json 路径 |

### Phase C

无文件改动（不做）。

---

## Phase A: 文档转换核心（pandoc + weasyprint）

### A.1 后端转换层

**新建 `gateway/convert.py`**

职责：封装 pandoc 子进程调用，把 `result.md` + `images/` 目录转换为目标格式文件。

```python
# gateway/convert.py 接口草案
from __future__ import annotations
import os
import subprocess
import tempfile
import zipfile
from pathlib import Path

SUPPORTED_FORMATS = ("md", "docx", "html", "pdf", "latex")

class ConversionError(Exception):
    pass

def convert_result(
    zip_path: str,
    fmt: str,
    out_path: str,
    pdf_engine: str = "weasyprint",
) -> str:
    """解 zip → pandoc 转换 → 写 out_path → 返回 out_path。
    
    - fmt="md" 时直接复制 zip 到 out_path（不调 pandoc）
    - 其他格式：解压到临时目录，pandoc 转换，清理临时目录
    - PDF 走 --pdf-engine=weasyprint
    - HTML 走 --embed-resources --standalone（图片内嵌成单文件）
    - docx/latex：标准调用，--resource-path 指向 images/ 父目录
    """
    if fmt not in SUPPORTED_FORMATS:
        raise ConversionError(f"unsupported format: {fmt}")
    if fmt == "md":
        shutil.copy(zip_path, out_path)
        return out_path
    # 1. 解 zip 到 tmp
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(tmp)
        md_path = os.path.join(tmp, "result.md")
        if not os.path.isfile(md_path):
            raise ConversionError("zip missing result.md")
        # 2. 构造 pandoc 命令
        cmd = ["pandoc", md_path, "-o", out_path, "--resource-path", tmp]
        if fmt == "html":
            cmd += ["--embed-resources", "--standalone"]
        elif fmt == "pdf":
            cmd += ["--pdf-engine", pdf_engine]
        # 3. 调用
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=120)
        except subprocess.CalledProcessError as e:
            raise ConversionError(f"pandoc failed: {e.stderr.decode()}")
        except subprocess.TimeoutExpired:
            raise ConversionError("pandoc timeout")
    return out_path
```

**关键设计点**：

- `--resource-path tmp`：pandoc 找 `images/page_xxxx.jpg` 的关键
- HTML 用 `--embed-resources --standalone`：图片内嵌 base64，单文件可发可存
- PDF 用 `--pdf-engine weasyprint`：weasyprint 走 HTML→PDF 路线，CJK 友好
- 临时目录用 `TemporaryDirectory` 自动清理
- 超时 120s（OCR 几百页的 PDF 转 docx 通常 < 30s，留余量）
- `ConversionError` 透传给 HTTP 层返回 500

### A.2 下载端点改造

**改 `gateway/server.py:206` `download_task`**

```python
@app.get("/api/v1/tasks/{task_id}/download", dependencies=[Depends(get_token)])
def download_task(task_id: str, format: str = "md"):
    # peer 代理透传 ?format=
    peer_url = _get_backend_for_task(task_id)
    if peer_url:
        peer = _find_peer(peer_url)
        if peer is None:
            raise HTTPException(500, f"peer {peer_url} not found")
        resp = proxy_request(peer, "GET", f"/api/v1/tasks/{task_id}/download?format={format}")
        if resp.status_code == 200:
            # 透传 peer 的响应（可能是 zip 也可能是转换后的单文件）
            media, filename = _media_for_format(format, task_id)
            return Response(content=resp.content, media_type=media,
                            headers={"Content-Disposition": f'attachment; filename="{filename}"'})
        raise HTTPException(resp.status_code, detail=resp.text)

    # 本地任务
    if format not in SUPPORTED_FORMATS:
        raise HTTPException(400, f"format must be one of {SUPPORTED_FORMATS}")

    with STATE.lock:
        task = STATE.tasks.get(task_id)
    if task is None:
        raise HTTPException(404, "task not found")
    if task.status == "failed":
        raise HTTPException(410, "task failed; no result zip available")
    if task.status != "completed":
        raise HTTPException(404, "task not completed")

    zip_path = os.path.join(STATE.workdir, "outputs", f"{task_id}.zip")
    if not os.path.isfile(zip_path):
        raise HTTPException(410, "zip missing")

    if format == "md":
        return FileResponse(zip_path, media_type="application/zip", filename=f"{task_id}.zip")

    # 非 md：转换 + 缓存
    out_path = os.path.join(STATE.workdir, "outputs", f"{task_id}.{format}")
    if not os.path.isfile(out_path):
        try:
            convert_result(zip_path, format, out_path, STATE.pandoc_pdf_engine)
        except ConversionError as e:
            raise HTTPException(500, f"conversion failed: {e}")

    media, filename = _media_for_format(format, task_id)
    return FileResponse(out_path, media_type=media, filename=filename)


def _media_for_format(fmt: str, task_id: str) -> tuple[str, str]:
    table = {
        "md":    ("application/zip",           f"{task_id}.zip"),
        "docx":  ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", f"{task_id}.docx"),
        "html":  ("text/html",                 f"{task_id}.html"),
        "pdf":   ("application/pdf",           f"{task_id}.pdf"),
        "latex": ("application/x-latex",       f"{task_id}.tex"),
    }
    return table[fmt]
```

**DELETE 同步改**（`server.py:237`）：

```python
# 现有清理逻辑之后追加：清转换缓存
for fmt in ("docx", "html", "pdf", "latex"):
    cached = os.path.join(STATE.workdir, "outputs", f"{task_id}.{fmt}")
    if os.path.isfile(cached):
        try: os.remove(cached)
        except OSError: pass
```

**CLI 参数**（`server.py:_parse_args`）：

```python
parser.add_argument(
    "--pandoc-pdf-engine",
    default="weasyprint",
    help="pandoc PDF engine (default: weasyprint; alt: xelatex, pdflatex)",
)
```

**STATE 加字段**（`state.py:_State`）：

```python
self.pandoc_pdf_engine: str = "weasyprint"
```

**`main()` 写入**：

```python
STATE.pandoc_pdf_engine = args.pandoc_pdf_engine
```

### A.3 前端下载菜单

**改 `clients/web/src/components/ResultViewer.vue:185`**

把单按钮换成下拉菜单。结构：

```vue
<div class="viewer__spacer" />
<div class="download-menu">
  <button class="btn btn--secondary btn--sm" @click="toggleDownloadMenu">
    下载 ▾
  </button>
  <div v-if="downloadMenuOpen" class="download-menu__items">
    <button @click="downloadAs('md')">ZIP (Markdown)</button>
    <button @click="downloadAs('docx')">Word (.docx)</button>
    <button @click="downloadAs('pdf')">PDF</button>
    <button @click="downloadAs('html')">HTML (单文件)</button>
    <button @click="downloadAs('latex')">LaTeX (.tex)</button>
  </div>
</div>
```

逻辑：

```ts
const downloadMenuOpen = ref(false)
function toggleDownloadMenu() { downloadMenuOpen.value = !downloadMenuOpen.value }
async function downloadAs(fmt: DownloadFormat) {
  downloadMenuOpen.value = false
  await api.value.downloadAs(props.task!.task_id, fmt)
}
```

**改 `clients/web/src/composables/useApi.ts`**

```ts
export type DownloadFormat = 'md' | 'docx' | 'html' | 'pdf' | 'latex'

async function downloadAs(taskId: string, fmt: DownloadFormat): Promise<void> {
  const r = await fetch(`${this.base}/api/v1/tasks/${taskId}/download?format=${fmt}`, {
    headers: this.authHeaders(),
  })
  if (!r.ok) {
    let detail = r.statusText
    try { detail = (await r.json()).detail ?? detail } catch {}
    throw new ApiClientError(r.status, detail)
  }
  const blob = await r.blob()
  // 解 Content-Disposition 取文件名
  const cd = r.headers.get('Content-Disposition') ?? ''
  const m = /filename="([^"]+)"/.exec(cd)
  const filename = m ? m[1] : `${taskId}.${fmt === 'md' ? 'zip' : fmt === 'latex' ? 'tex' : fmt}`
  // 触发浏览器下载
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url; a.download = filename
  document.body.appendChild(a); a.click(); document.body.removeChild(a)
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
```

**改 `clients/web/src/types/api.ts`**

```ts
export type DownloadFormat = 'md' | 'docx' | 'html' | 'pdf' | 'latex'
```

### A.4 CLI 下载格式参数

**改 `clients/python-cli/src/ocr_client/cli.py:185` `cmd_download` 与 `build_parser`**

argparse 加：

```python
p_dl.add_argument(
    "--format",
    choices=("md", "docx", "html", "pdf", "latex"),
    default="md",
    help="output format (default: md = original ZIP)",
)
```

`_download_and_extract` 改造：

```python
def _download_and_extract(console, server, token, task_id, out_dir, fmt="md"):
    out_root = Path(out_dir).mkdir(parents=True, exist_ok=True)
    # 状态终态检查不变
    # 下载请求加 ?format=
    url = f"{server}/api/v1/tasks/{task_id}/download?format={fmt}"
    # ...
    if fmt == "md":
        # 现有逻辑：存 zip + 解压
        zip_path = out_root / f"{task_id}.zip"
        # ... 下载 + extractall
    else:
        # 单文件：存 {task_id}.{ext}
        ext = {"docx":"docx","html":"html","pdf":"pdf","latex":"tex"}[fmt]
        file_path = out_root / f"{task_id}.{ext}"
        # 流式下载到 file_path，不解压
        _print(console, f"[bold green]saved[/bold green] {file_path}")
```

### A.5 契约与文档

**`API_CONTRACT.md` §4.4 改造**：

```markdown
### 4.4 `GET /api/v1/tasks/{task_id}/download?format={md|docx|html|pdf|latex}`（鉴权）

**Query 参数**：
- `format`：可选，默认 `md`。值域 `md / docx / html / pdf / latex`

**Response 200**（format=md，原行为）：
- Content-Type: application/zip
- body: ZIP(result.md + images/)

**Response 200**（format=docx|html|pdf|latex）：
- Content-Type 见下表
- body: 转换后的单文件
- 转换结果缓存在 `api_workdir/outputs/{task_id}.{ext}`，下次请求相同格式直接命中缓存
- DELETE 任务时一并清除所有格式缓存

| format | Content-Type | 扩展名 |
|--------|--------------|--------|
| md | application/zip | .zip |
| docx | application/vnd.openxmlformats-officedocument.wordprocessingml.document | .docx |
| html | text/html | .html |
| pdf | application/pdf | .pdf |
| latex | application/x-latex | .tex |

**错误**：
- 400 format 不在值域内
- 404 task 不存在 / 未完成
- 410 task 已 failed
- 500 pandoc 转换失败（错误细节在 detail）
```

**`README_API.md` 新增章节"文档转换输出"**：

```markdown
## 文档转换输出

服务端集成 pandoc，支持把 OCR 结果转换为 5 种格式下载：

| 格式 | 说明 | 安装依赖 |
|------|------|---------|
| md | 原始 ZIP（result.md + images/） | 无 |
| docx | Word 文档 | pandoc |
| html | 单文件 HTML，图片内嵌 | pandoc |
| pdf | PDF 文档 | pandoc + weasyprint |
| latex | LaTeX 源码 | pandoc |

### 安装

服务端宿主：

    apt install pandoc libpango-1.0-0 libpangoft2-1.0-0
    uv pip install weasyprint

### 使用

CLI:

    ocr-client download <task_id> --format docx --out ./out
    ocr-client download <task_id> --format pdf --out ./out

浏览器：在结果预览页点"下载 ▾"选格式。

### PDF 引擎切换

默认 weasyprint（HTML 路线，CJK 友好）。如需 xelatex（学术排版更精细）：

    python -m gateway.server --pandoc-pdf-engine xelatex

需自行安装 TeX Live。
```

**`Dockerfile` 加系统依赖**：

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends \
    pandoc libpango-1.0-0 libpangoft2-1.0-0 \
    && rm -rf /var/lib/apt/lists/*
```

**`requirements-api.txt` 追加**：

```
weasyprint>=60
```

### A.6 依赖与部署

**先决条件检查清单**（Phase A 开工前必须跑通）：

1. `pandoc --version` 在宿主上可用
   - 否则：`sudo apt install pandoc`
2. weasyprint 可用
   - `uv pip install weasyprint`
   - `apt install libpango-1.0-0 libpangoft2-1.0-0`
   - 验证：`python -c "import weasyprint; weasyprint.HTML(string='<h1>test</h1>').write_pdf('/tmp/t.pdf')"`
3. 用现有 `api_workdir/outputs/*.zip` 里的某个 result.md 手跑一次 pandoc：
   - `unzip -d /tmp/test {some_task_id}.zip`
   - `pandoc /tmp/test/result.md -o /tmp/test.docx --resource-path /tmp/test`
   - 验证 docx 能被 LibreOffice / Word 打开
4. CJK 字体检查：`fc-list :lang=zh` 应有输出；否则 PDF 中文会变方块
   - 装：`apt install fonts-noto-cjk`

**Docker 镜像体积预估**：

- pandoc：~150MB
- libpango：~10MB
- weasyprint + 依赖：~100MB
- 字体 fonts-noto-cjk：~120MB
- 合计 +~380MB（可接受）

### A.7 验收

**Phase A 端到端验收脚本**：

```bash
# 前置：server 已起，pandoc/weasyprint 已装
TOKEN=$(cat ~/.ocr_token)
SERVER=http://127.0.0.1:10001

# 1. 上传一个 PDF
TASK_ID=$(curl -s -X POST "$SERVER/api/v1/tasks" \
    -H "Authorization: Bearer $TOKEN" \
    -F "file=@LEMMA_Learning_Language-Conditioned_Multi-Robot_Manipulation.pdf" \
    | python -c "import sys,json;print(json.load(sys.stdin)['task_id'])")
echo "task_id=$TASK_ID"

# 2. 等完成
while true; do
    STATUS=$(curl -s "$SERVER/api/v1/tasks/$TASK_ID" -H "Authorization: Bearer $TOKEN" | python -c "import sys,json;print(json.load(sys.stdin)['status'])")
    [ "$STATUS" = "completed" ] && break
    [ "$STATUS" = "failed" ] && { echo "task failed"; exit 1; }
    sleep 5
done

# 3. 五种格式各下载一次
for FMT in md docx html pdf latex; do
    echo "=== downloading $FMT ==="
    EXT=$([ "$FMT" = "md" ] && echo zip || ([ "$FMT" = "latex" ] && echo tex || echo $FMT))
    curl -s "$SERVER/api/v1/tasks/$TASK_ID/download?format=$FMT" \
        -H "Authorization: Bearer $TOKEN" \
        -o /tmp/test_$TASK_ID.$EXT
    # 验证文件有效性
    case $FMT in
        md)    unzip -t /tmp/test_$TASK_ID.zip > /dev/null && echo "zip OK" ;;
        docx)  python -c "import docx; docx.Document('/tmp/test_$TASK_ID.docx')" && echo "docx OK" ;;
        pdf)   head -c 4 /tmp/test_$TASK_ID.pdf | xxd | grep -q "2550 4446" && echo "pdf OK" ;;
        html)  head -c 20 /tmp/test_$TASK_ID.html | grep -q "<!DOCTYPE\|<html" && echo "html OK" ;;
        latex) grep -q "\\\\documentclass\|\\\\begin{document}" /tmp/test_$TASK_ID.tex && echo "latex OK" ;;
    esac
done

# 4. 缓存命中验证：第二次请求 docx 应秒回
time curl -s "$SERVER/api/v1/tasks/$TASK_ID/download?format=docx" -H "Authorization: Bearer $TOKEN" -o /dev/null

# 5. DELETE 清缓存
curl -s -X DELETE "$SERVER/api/v1/tasks/$TASK_ID" -H "Authorization: Bearer $TOKEN"
ls api_workdir/outputs/$TASK_ID.* 2>/dev/null || echo "cache cleaned OK"

# 6. peer 代理透传 ?format=（如有 peer 环境）
# curl peer 节点的 download?format=docx，验证返回 docx
```

**前端验收**：

- 打开结果预览页 → "下载 ▾" 展开 → 5 个选项
- 点 DOCX → 浏览器下载 `{task_id}.docx`
- 点 PDF → 浏览器下载 `{task_id}.pdf`，打开内容完整、图片在位
- 点 HTML → 下载单文件，双击在浏览器打开，图片内嵌可见

**CLI 验收**：

- `ocr-client download <id> --format docx --out ./out`
- `ls ./out/{id}.docx` 存在且有效

---

## Phase B: 小团队多用户 + 持久化

### B.1 用户注册表（配置文件）

**新建 `gateway/users.py`**

```python
# gateway/users.py 接口草案
from __future__ import annotations
import json
import os
import threading
import time
from dataclasses import dataclass
from typing import Optional

@dataclass
class UserInfo:
    token: str
    owner: str

class UserRegistry:
    """从 json 文件读 token→owner 映射，支持热加载。
    
    文件格式 (~/.ocr_tokens.json):
        {
          "tokens": [
            {"token": "t1xxx", "owner": "alice"},
            {"token": "t2xxx", "owner": "bob"}
          ]
        }
    
    热加载：每次 lookup 检查 mtime，变了就重读。
    单 token 回退：文件不存在时，使用 OCR_API_TOKEN env，owner="self"。
    """
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._path: str = ""
        self._mtime: float = 0.0
        self._tokens: dict[str, str] = {}  # token -> owner
        self._single_token: Optional[str] = None  # 回退模式
    
    def configure(self, tokens_file: Optional[str], env_token: Optional[str]) -> None:
        with self._lock:
            self._path = tokens_file or os.path.expanduser("~/.ocr_tokens.json")
            self._single_token = env_token
            self._reload_if_needed()
    
    def _reload_if_needed(self) -> None:
        """检查 mtime，变了就重读。调用者需持锁。"""
        if not os.path.isfile(self._path):
            return  # 走单 token 回退
        mtime = os.path.getmtime(self._path)
        if mtime == self._mtime:
            return
        with open(self._path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self._tokens = {item["token"]: item["owner"] for item in data.get("tokens", [])}
        self._mtime = mtime
    
    def lookup(self, token: str) -> Optional[str]:
        """返回 owner，找不到返回 None。"""
        with self._lock:
            self._reload_if_needed()
            if self._tokens:
                return self._tokens.get(token)
            # 单 token 回退
            if self._single_token and token == self._single_token:
                return "self"
            return None
    
    def is_multi_user_mode(self) -> bool:
        with self._lock:
            self._reload_if_needed()
            return bool(self._tokens)
```

**server.py 启动时配置**：

```python
STATE.users = UserRegistry()
STATE.users.configure(args.tokens_file, os.environ.get("OCR_API_TOKEN", "").strip() or None)
```

**CLI 参数**：

```python
parser.add_argument(
    "--tokens-file",
    default=os.environ.get("OCR_TOKENS_FILE"),
    help="path to tokens json (default: $OCR_TOKENS_FILE or ~/.ocr_tokens.json)",
)
```

**`~/.ocr_tokens.json` 示例**：

```json
{
  "tokens": [
    {"token": "alice_xxx_secretpass", "owner": "alice"},
    {"token": "bob_yyy_secretpass",   "owner": "bob"},
    {"token": "carol_zzz_secretpass", "owner": "carol"}
  ]
}
```

权限 `chmod 600 ~/.ocr_tokens.json`。

### B.2 鉴权改造

**改 `gateway/auth.py`**

```python
from .users import UserRegistry

def get_token(authorization: Optional[str] = Header(default=None)) -> str:
    """返回 owner；401 if invalid。"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "invalid token")
    candidate = authorization[len("Bearer "):]
    owner = STATE.users.lookup(candidate)
    if owner is None:
        raise HTTPException(401, "invalid token")
    return owner  # 注意：现在返回的是 owner，不是 token

# 旧调用点需要改：原来 Depends(get_token) 拿到的是 token 字符串，
# 现在拿到的是 owner 字符串。所有用 Depends(get_token) 的端点都要改名:
#   owner: str = Depends(get_token)
```

**所有端点签名调整**：

```python
# server.py
@app.post("/api/v1/tasks", status_code=202, dependencies=[Depends(get_token)])
async def create_task(
    owner: str = Depends(get_token),  # 改这里
    file: UploadFile = File(...),
    ...
):
    ...
    task = TaskState(task_id=task_id, owner=owner, ...)
```

注意：原来用 `dependencies=[Depends(get_token)]` 的端点（不取返回值），改成 `owner: str = Depends(get_token)` 取返回值。`/health` 不动。

### B.3 任务状态扩展 owner

**改 `gateway/state.py`**

```python
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
    owner: str = ""              # ★ 新增
    created_at: str = field(default_factory=_now_iso)
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    pdf_path: str = ""
    work_subdir: str = ""
    backend_url: str = ""
    pdf_name: str = ""           # ★ 新增（持久化用，重启后原 pdf_path 已无意义）

def _task_to_dict(task: TaskState) -> dict:
    d = {
        "task_id": task.task_id,
        "status": task.status,
        "progress": round(task.progress, 4),
        "current_page": task.current_page,
        "total_pages": task.total_pages,
        "image_mode": task.image_mode,
        "concurrency": task.concurrency,
        "error": task.error,
        "owner": task.owner,       # ★ 输出
        "created_at": task.created_at,
        "started_at": task.started_at,
        "finished_at": task.finished_at,
    }
    if task.backend_url:
        d["backend_url"] = task.backend_url
    return d
```

**`_State` 加字段**：

```python
class _State:
    def __init__(self) -> None:
        ...
        self.users: UserRegistry = UserRegistry()  # ★
```

### B.4 列表端点与 /me 端点

**改 `gateway/server.py`**

```python
@app.get("/api/v1/me", dependencies=[Depends(get_token)])
def me(owner: str = Depends(get_token)) -> dict:
    return {"owner": owner}

@app.get("/api/v1/tasks", dependencies=[Depends(get_token)])
def list_tasks(owner: str = Depends(get_token), scope: str = "mine") -> dict:
    if scope not in ("mine", "all"):
        raise HTTPException(400, "scope must be 'mine' or 'all'")
    with STATE.lock:
        items = list(STATE.tasks.values())
    if scope == "mine":
        items = [t for t in items if t.owner == owner]
    # 按 created_at 倒序
    items.sort(key=lambda t: t.created_at, reverse=True)
    return {
        "tasks": [_task_to_dict(t) for t in items],
        "count": len(items),
        "scope": scope,
    }
```

**注意**：`GET /api/v1/tasks`（无路径参数）和 `GET /api/v1/tasks/{task_id}` 不冲突，FastAPI 路由按声明顺序匹配，确保 list 端点声明在 detail 端点之前（或 FastAPI 自动按特异性匹配，两者都能正确路由）。

**peer 代理**：列表端点不代理（只列本地任务）。peer 模式下用户看到的列表只含本节点任务。如需聚合，后续扩展，本次不做。

### B.5 sqlite 轻量持久化

**新建 `gateway/persist.py`**

```python
# gateway/persist.py 接口草案
from __future__ import annotations
import os
import sqlite3
import threading
from typing import Optional
from .state import TaskState, _now_iso

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    status TEXT NOT NULL,
    pdf_name TEXT NOT NULL,
    image_mode TEXT NOT NULL,
    concurrency INTEGER NOT NULL,
    progress REAL NOT NULL,
    current_page INTEGER NOT NULL,
    total_pages INTEGER NOT NULL,
    error TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    backend_url TEXT
);
"""

class Persistence:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        with self._lock:
            conn = sqlite3.connect(db_path)
            conn.executescript(_SCHEMA)
            conn.commit()
            conn.close()
    
    def save_task(self, task: TaskState) -> None:
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            conn.execute(
                """INSERT OR REPLACE INTO tasks
                   (task_id, owner, status, pdf_name, image_mode, concurrency,
                    progress, current_page, total_pages, error,
                    created_at, started_at, finished_at, backend_url)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (task.task_id, task.owner, task.status, task.pdf_name,
                 task.image_mode, task.concurrency, task.progress,
                 task.current_page, task.total_pages, task.error,
                 task.created_at, task.started_at, task.finished_at,
                 task.backend_url or "")
            )
            conn.commit()
            conn.close()
    
    def load_all(self) -> list[TaskState]:
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM tasks").fetchall()
            conn.close()
        return [TaskState(
            task_id=r["task_id"], owner=r["owner"], status=r["status"],
            pdf_name=r["pdf_name"], image_mode=r["image_mode"],
            concurrency=r["concurrency"], progress=r["progress"],
            current_page=r["current_page"], total_pages=r["total_pages"],
            error=r["error"], created_at=r["created_at"],
            started_at=r["started_at"], finished_at=r["finished_at"],
            backend_url=r["backend_url"] or "",
        ) for r in rows]
    
    def delete_task(self, task_id: str) -> None:
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            conn.execute("DELETE FROM tasks WHERE task_id=?", (task_id,))
            conn.commit()
            conn.close()
```

**改 `gateway/tasks.py`**（worker 状态变更处插桩）

需要在所有 `task.status = ...` 赋值后调用 `STATE.persist.save_task(task)`。具体位置：

- `queued` 入队时（`server.py:create_task`）
- `running` 开始时（worker_loop 拿到任务）
- `current_page` / `progress` 更新时（进度轮询）—— 可选，频率高，建议只在 running 起止和终态写
- `completed` / `failed` 时
- DELETE 时（`server.py:delete_task`）调 `persist.delete_task`

**启动时恢复**（`server.py:main()`）：

```python
STATE.persist = Persistence(os.path.join(STATE.workdir, "tasks.db"))
for task in STATE.persist.load_all():
    if task.status == "running":
        task.status = "failed"
        task.error = "server restarted"
        task.finished_at = _now_iso()
        STATE.persist.save_task(task)
    STATE.tasks[task.task_id] = task
print(f"[server] recovered {len(STATE.tasks)} tasks from sqlite", flush=True)
```

**注意**：恢复时 `pdf_path` / `work_subdir` 已无意义（tmp 被清），置空。`status == "completed"` 的任务 zip 还在 `outputs/`，可正常下载。

**STATE 加字段**：

```python
self.persist: Optional[Persistence] = None
```

### B.6 前端多用户界面

**改 `clients/web/src/components/SettingsBar.vue`**

token 输入后调 `/api/v1/me` 显示当前用户：

```vue
<div class="settings__user" v-if="currentUser">
  当前用户: <strong>{{ currentUser }}</strong>
</div>
```

```ts
const currentUser = ref<string>('')
async function fetchMe() {
  try {
    const data = await api.value.whoami()
    currentUser.value = data.owner
  } catch { currentUser.value = '' }
}
watch(() => settings.value.token, fetchMe)
```

**改 `clients/web/src/components/TaskCard.vue`**

加 owner 徽章：

```vue
<div class="taskcard__owner" v-if="task.owner">
  <span class="badge badge--owner">{{ task.owner }}</span>
</div>
```

**改 `clients/web/src/components/TaskList.vue`**

加 scope 切换和刷新按钮：

```vue
<div class="tasklist__controls">
  <label><input type="radio" v-model="scope" value="mine" /> 只看我的</label>
  <label><input type="radio" v-model="scope" value="all" /> 看全部</label>
  <button @click="refreshFromServer">从服务端刷新</button>
</div>
```

```ts
const scope = ref<'mine' | 'all'>('mine')
async function refreshFromServer() {
  const data = await api.value.listTasks(scope.value)
  // 合并到 useTaskStore
  for (const t of data.tasks) {
    taskStore.upsert(t)
  }
}
```

**改 `clients/web/src/composables/useApi.ts`**

```ts
async function whoami(): Promise<{ owner: string }> {
  const r = await fetch(`${this.base}/api/v1/me`, { headers: this.authHeaders() })
  if (!r.ok) throw new ApiClientError(r.status, await this.parseDetail(r))
  return r.json()
}

async function listTasks(scope: 'mine' | 'all' = 'mine'): Promise<TaskListResponse> {
  const r = await fetch(`${this.base}/api/v1/tasks?scope=${scope}`, { headers: this.authHeaders() })
  if (!r.ok) throw new ApiClientError(r.status, await this.parseDetail(r))
  return r.json()
}
```

**改 `clients/web/src/types/api.ts`**

```ts
export interface TaskInfo {
  // 现有字段...
  owner: string  // ★ 新增
}

export interface TaskListResponse {
  tasks: TaskInfo[]
  count: number
  scope: 'mine' | 'all'
}
```

### B.7 CLI 多用户命令

**改 `clients/python-cli/src/ocr_client/cli.py`**

新增两个子命令：

```python
p_ls = sub.add_parser("list", help="list tasks")
common_auth(p_ls)
p_ls.add_argument("--scope", choices=("mine", "all"), default="mine")
p_ls.add_argument("--limit", type=int, default=50)
p_ls.set_defaults(func=cmd_list)

p_me = sub.add_parser("whoami", help="show current user")
common_auth(p_me)
p_me.set_defaults(func=cmd_whoami)
```

```python
def cmd_list(args):
    data = api.list_tasks(server, token, args.scope)
    # 表格输出：task_id | status | owner | pdf_name | created_at
    # rich 表格 或 纯文本
    ...

def cmd_whoami(args):
    data = api.whoami(server, token)
    print(f"owner: {data['owner']}")
    return 0
```

**改 `clients/python-cli/src/ocr_client/api.py`**

```python
def list_tasks(server, token, scope="mine"):
    r = requests.get(f"{server}/api/v1/tasks",
                     params={"scope": scope},
                     headers=build_headers(token), timeout=10.0)
    return check_resp(r)

def whoami(server, token):
    r = requests.get(f"{server}/api/v1/me",
                     headers=build_headers(token), timeout=10.0)
    return check_resp(r)
```

### B.8 契约与文档

**`API_CONTRACT.md` 改造**：

§2 鉴权 —— 加多 token 配置文件：

```markdown
## 2. 鉴权

支持两种模式：

### 2.1 单 token 模式（向后兼容）

环境变量 `OCR_API_TOKEN`。owner 固定为 "self"。

### 2.2 多 token 模式

配置文件 `~/.ocr_tokens.json`（或 `--tokens-file` 指定路径）：

    {
      "tokens": [
        {"token": "t1xxx", "owner": "alice"},
        {"token": "t2xxx", "owner": "bob"}
      ]
    }

- 文件不存在时自动回退到单 token 模式
- 文件 mtime 变化时自动热加载，无需重启
- owner 用于任务归属和列表过滤
- 文件权限建议 `chmod 600`
```

§3 状态机 —— 加 owner 字段：

```markdown
| `owner` | string | 任务所属用户名（单 token 模式为 "self"）|
```

新增 §4.6 列表端点：

```markdown
### 4.6 `GET /api/v1/tasks?scope=mine|all`（鉴权）

返回任务列表。

**Query**：
- `scope`：可选，默认 `mine`。`mine` 只返回当前 owner 的任务，`all` 返回全部

**Response 200**：
    {
      "tasks": [ <task状态对象>, ... ],
      "count": 12,
      "scope": "mine"
    }

按 `created_at` 倒序排列。
```

新增 §4.7 `/me` 端点：

```markdown
### 4.7 `GET /api/v1/me`（鉴权）

返回当前 token 对应的用户信息。

**Response 200**：
    { "owner": "alice" }
```

§6 文件布局 —— 加 `tasks.db`：

```markdown
./api_workdir/
├── tmp/<task_id>/                 # 中间产物（任务完成后清理）
├── outputs/<task_id>.zip          # 最终结果 MD+图片
├── outputs/<task_id>.{docx,html,pdf,tex}  # 转换缓存（Phase A）
├── logs/<task_id>_sglang.log      # SGLang 日志
└── tasks.db                       # sqlite 任务持久化（Phase B）
```

**`README_API.md` 新增"多用户配置"章节**：

```markdown
## 多用户配置（小团队）

### 配置文件

创建 `~/.ocr_tokens.json`：

    {
      "tokens": [
        {"token": "alice_xxx", "owner": "alice"},
        {"token": "bob_yyy",   "owner": "bob"}
      ]
    }

    chmod 600 ~/.ocr_tokens.json

启动 server（自动识别文件）：

    python -m gateway.server --port 10001

或指定路径：

    python -m gateway.server --tokens-file /path/to/tokens.json

### 客户端使用

每位用户用自己的 token：

    export OCR_API_TOKEN=alice_xxx
    ocr-client whoami             # → owner: alice
    ocr-client upload doc.pdf     # 任务归属 alice
    ocr-client list --scope mine  # 只看自己的
    ocr-client list --scope all   # 看全部

### 单 token 回退

未配置 tokens.json 时，使用 `OCR_API_TOKEN` 环境变量，owner="self"。
现有部署无需任何改动。
```

**`docs/project_notes/decisions.md` 加两条 ADR**：

```markdown
## ADR-007: weasyprint 作为默认 PDF 引擎（2026-06-30）

**上下文**：Phase A 文档转换需要 PDF 引擎。候选：weasyprint / xelatex / pdflatex / wkhtmltopdf

**决策**：默认 weasyprint，可通过 `--pandoc-pdf-engine` 切换

**理由**：
- pip 安装，无系统级 TeX 依赖
- ~100MB（vs TeX Live 500MB-1GB）
- HTML→PDF 路线，CJK 友好（配 noto-cjk 字体）
- pandoc 原生支持 `--pdf-engine weasyprint`

**替代方案**：
- xelatex：学术排版更精细，但 TeX Live 太重，Docker 镜像翻倍
- pdflatex：不支持 CJK，排除

**后果**：Dockerfile 需装 libpango；用户要 xelatex 可自装 TeX Live 后切换

## ADR-008: 多 token 用配置文件 + sqlite 持久化（2026-06-30）

**上下文**：Phase B 小团队 2-10 人，需多用户标识和任务持久化

**决策**：
- Token 配置：`~/.ocr_tokens.json` 文件（非 env，非 DB）
- 持久化：sqlite（stdlib `sqlite3`，无新依赖）
- 列表可见性：mine/all 两档，不做细粒度权限

**理由**：
- env 多 token 格式丑（`OCR_API_TOKENS="t1:alice,t2:bob"`），转义/特殊字符难处理
- 配置文件支持热加载，改 token 不重启
- sqlite 是 stdlib，零依赖；JSON 文件并发写有竞争，sqlite ACID 安全
- 2-10 人信任模型，all 即看全部，无需 RBAC

**替代方案**：
- env 多 token：被否决（格式丑，长度限制）
- PostgreSQL/MySQL：过度设计
- JSON 文件持久化：并发写不安全
- 完整 RBAC：2-10 人用不上

**后果**：新增 `gateway/users.py` + `gateway/persist.py`；server 启动多一步加载
```

### B.9 验收

**Phase B 端到端验收脚本**：

```bash
# 1. 准备 tokens.json
cat > /tmp/tokens_test.json <<'EOF'
{
  "tokens": [
    {"token": "alice_test_token", "owner": "alice"},
    {"token": "bob_test_token",   "owner": "bob"}
  ]
}
EOF
chmod 600 /tmp/tokens_test.json

# 2. 启动 server（用测试端口避免冲突）
python -m gateway.server --port 10099 --workdir /tmp/uocr_b_test \
    --tokens-file /tmp/tokens_test.json --model-dir ./Unlimited-OCR &
SERVER=http://127.0.0.1:10099
sleep 3

# 3. /me 端点
curl -s $SERVER/api/v1/me -H "Authorization: Bearer alice_test_token" | grep alice
curl -s $SERVER/api/v1/me -H "Authorization: Bearer bob_test_token"   | grep bob
curl -s -o /dev/null -w "%{http_code}\n" $SERVER/api/v1/me -H "Authorization: Bearer wrong"  # 401

# 4. alice 上传一个任务
TASK_A=$(curl -s -X POST $SERVER/api/v1/tasks \
    -H "Authorization: Bearer alice_test_token" \
    -F "file=@LEMMA_Learning_Language-Conditioned_Multi-Robot_Manipulation.pdf" \
    | python -c "import sys,json;print(json.load(sys.stdin)['task_id'])")

# 5. 立即查 owner
curl -s $SERVER/api/v1/tasks/$TASK_A -H "Authorization: Bearer alice_test_token" \
    | python -c "import sys,json;d=json.load(sys.stdin);assert d['owner']=='alice';print('owner OK')"

# 6. 列表 scope=mine
curl -s "$SERVER/api/v1/tasks?scope=mine" -H "Authorization: Bearer alice_test_token" \
    | python -c "import sys,json;d=json.load(sys.stdin);assert all(t['owner']=='alice' for t in d['tasks']);print('mine filter OK')"

# 7. bob 看 mine 应该看不到 alice 的任务
curl -s "$SERVER/api/v1/tasks?scope=mine" -H "Authorization: Bearer bob_test_token" \
    | python -c "import sys,json;d=json.load(sys.stdin);assert all(t['owner']=='bob' for t in d['tasks']);print('isolation OK')"

# 8. bob 看 all 能看到 alice 的
curl -s "$SERVER/api/v1/tasks?scope=all" -H "Authorization: Bearer bob_test_token" \
    | python -c "import sys,json;d=json.load(sys.stdin);assert any(t['owner']=='alice' for t in d['tasks']);print('all scope OK')"

# 9. 持久化：kill server，重启，列表应还在
kill %1; sleep 2
python -m gateway.server --port 10099 --workdir /tmp/uocr_b_test \
    --tokens-file /tmp/tokens_test.json --model-dir ./Unlimited-OCR &
sleep 3
curl -s "$SERVER/api/v1/tasks?scope=all" -H "Authorization: Bearer alice_test_token" \
    | python -c "import sys,json;d=json.load(sys.stdin);assert d['count']>0;print('persist OK')"

# 10. 重启时 running 的应标 failed
curl -s $SERVER/api/v1/tasks/$TASK_A -H "Authorization: Bearer alice_test_token" \
    | python -c "import sys,json;d=json.load(sys.stdin);print(d['status'])"  # completed 或 failed（看任务是否完成）

# 11. 热加载：改 tokens.json，不重启
cat > /tmp/tokens_test.json <<'EOF'
{
  "tokens": [
    {"token": "alice_test_token", "owner": "alice"},
    {"token": "dave_new_token",   "owner": "dave"}
  ]
}
EOF
sleep 1
curl -s $SERVER/api/v1/me -H "Authorization: Bearer dave_new_token" | grep dave  # 应成功
curl -s -o /dev/null -w "%{http_code}\n" $SERVER/api/v1/me -H "Authorization: Bearer bob_test_token"  # 401（bob 已删）

# 12. 清理
kill %1; rm -rf /tmp/uocr_b_test /tmp/tokens_test.json
```

**前端验收**：

- token 输入 alice 的 → 顶部显示"当前用户: alice"
- 上传一个任务 → 卡片显示 owner=alice 徽章
- 切到"看全部" → 能看到其他 owner 的任务
- 切回"只看我的" → 只看 alice 的
- 刷新按钮 → 从服务端拉最新列表

**CLI 验收**：

- `ocr-client whoami` → `owner: alice`
- `ocr-client list --scope mine` → 表格只列 alice 的任务
- `ocr-client list --scope all` → 列全部

---

## Phase C: 知识库导出 hook

**不做。**

用户明确选择"不做 hook"。知识库方向（RAG vs wiki vs Obsidian 同步）未定，等后续方向明确后再补导出接口。当前架构不预留任何 hook 代码，避免假抽象。

后续如需做，可考虑的形态（不在本次方案内）：

- 外部 shell 脚本：`OCR_EXPORT_HOOK=/path/script.sh`，server 把 `result_dir` 作为 `$1` 传给它
- Python 插件：entry point 形式
- 直接加 `/api/v1/tasks/{id}/export-to-obsidian` 端点

---

## 执行顺序与依赖

```
Phase A (1-1.5 天)
  ├─ A.1 后端 convert.py
  ├─ A.2 下载端点 + CLI 参数
  ├─ A.3 前端下载菜单
  ├─ A.4 CLI --format
  ├─ A.5 契约/文档
  ├─ A.6 依赖安装 (pandoc, weasyprint)
  └─ A.7 验收
        │
        ▼
Phase B (1.5-2 天)  ← 依赖 A 完成后，owner 字段和持久化一起做
  ├─ B.1 users.py + tokens.json
  ├─ B.2 auth.py 改造
  ├─ B.3 state.py owner 字段
  ├─ B.4 列表 + /me 端点
  ├─ B.5 persist.py sqlite
  ├─ B.6 前端多用户
  ├─ B.7 CLI list/whoami
  ├─ B.8 契约/文档
  └─ B.9 验收
        │
        ▼
Phase C (不做)
```

**并行可能性**：A.3 前端 和 A.4 CLI 可并行，A.1 后端 是它们的前置。B.6 前端 和 B.7 CLI 可并行，B.1-B.5 后端是前置。

**总估时**：2.5-3.5 天（单人顺序做）。

---

## 决策记录

### ADR-007: weasyprint 作为默认 PDF 引擎

- **日期**：2026-06-30
- **上下文**：Phase A 文档转换需 PDF 引擎
- **决策**：默认 weasyprint，`--pandoc-pdf-engine` 可切换
- **理由**：pip 装 ~100MB vs TeX Live 500MB-1GB；HTML→PDF 路线 CJK 友好；pandoc 原生支持
- **替代**：xelatex（学术精细但太重）、pdflatex（不支持 CJK）
- **后果**：Dockerfile 装 libpango；用户要 xelatex 自装 TeX Live

### ADR-008: 多 token 配置文件 + sqlite 持久化

- **日期**：2026-06-30
- **上下文**：Phase B 小团队 2-10 人多用户
- **决策**：tokens.json 配置文件 + sqlite 持久化 + mine/all 两档可见性
- **理由**：env 多 token 格式丑；配置文件支持热加载；sqlite 是 stdlib 零依赖；2-10 人无需 RBAC
- **替代**：env 多 token（否决）、PostgreSQL（过度设计）、JSON 文件持久化（并发写不安全）、完整 RBAC（用不上）
- **后果**：新增 `gateway/users.py` + `gateway/persist.py`

### ADR-009: 知识库导出 hook 暂不做

- **日期**：2026-06-30
- **上下文**：用户设定第二层目标"PDF→MD→知识库"，但 RAG vs wiki vs Obsidian 方向未定
- **决策**：本次完全不实现 hook，不留接口
- **理由**：假抽象比没接口更糟；方向定了再补，三种形态（shell/Python插件/直接端点）都能后加
- **后果**：Phase C 无代码改动

### ADR-010: 转换在服务端完成

- **日期**：2026-06-30
- **上下文**：pandoc 转换可在服务端或客户端做
- **决策**：服务端转换
- **理由**：服务化意义所在；用户无需本地装 pandoc/weasyprint；转换结果可缓存复用
- **替代**：客户端转换（用户都得装 pandoc，违背服务化）
- **后果**：服务端需装 pandoc + weasyprint；Dockerfile 体积 +~380MB

### ADR-011: 默认格式 md 保持向后兼容

- **日期**：2026-06-30
- **上下文**：下载端点加 `?format=` 参数
- **决策**：默认 `md`，返回原 ZIP
- **理由**：现有 CLI/前端不传 `?format=` 也能正常工作，零破坏
- **替代**：默认改成新格式（破坏所有现有客户端）
- **后果**：客户端需主动传 `?format=` 才能拿转换后格式

---

## 风险与回避

### 风险 1: pandoc 找不到 images/

**症状**：转换后的 docx/html 里图片是破图或链接断

**回避**：

- `--resource-path` 参数指向解压目录（tmp 目录，里面有 `result.md` 和 `images/`）
- 验收脚本 A.7 第 3 步用手跑 pandoc 验证
- HTML 用 `--embed-resources` 把图片内嵌成 base64，不依赖外部文件

### 风险 2: weasyprint CJK 字体缺失

**症状**：PDF 中文变方块

**回避**：

- Dockerfile 加 `fonts-noto-cjk`
- 宿主部署 README 提醒装字体
- 验收脚本检查 PDF 中文渲染

### 风险 3: pandoc 超时

**症状**：大 PDF（几百页）转换超 120s

**回避**：

- 超时 120s（大文档通常 < 30s，留余量）
- 超时返回 500，用户可重试
- 缓存命中后不再转换

### 风险 4: 转换缓存磁盘膨胀

**症状**：一个任务 5 种格式都下载，outputs/ 里堆 5 个文件

**回避**：

- DELETE 时清所有格式缓存
- 后续可加 LRU 清理（本次不做，2-10 人场景磁盘够用）

### 风险 5: tokens.json 热加载竞态

**症状**：改文件时正好有请求在 lookup

**回避**：

- `UserRegistry._lock` 保护，lookup 时持锁重读
- json 原子读（读时文件可能写一半）—— 用 `os.path.getmtime` 判断变化，重读时 `json.load` 如果失败保持旧映射，下次再试
- 生产建议用 `mv` 替换文件（原子操作）而非原地改

### 风险 6: sqlite 并发写

**症状**：worker 线程和 HTTP 线程同时写

**回避**：

- `Persistence._lock` 串行化所有写操作
- sqlite 默认 WAL 模式可加 `PRAGMA journal_mode=WAL`（可选）
- 单进程内并发量低（worker 一个线程 + HTTP 多线程但写频率低），不会瓶颈

### 风险 7: 重启时 running 任务标 failed 但 zip 还在

**症状**：任务实际已跑完只是没来得及写 completed，重启后标 failed，但 zip 文件在 outputs/

**回避**：

- 重启恢复时检查 `outputs/{task_id}.zip` 是否存在，存在则标 completed 而非 failed
- 代码：
  ```python
  if task.status == "running":
      zip_path = os.path.join(STATE.workdir, "outputs", f"{task.task_id}.zip")
      if os.path.isfile(zip_path):
          task.status = "completed"
          task.progress = 1.0
      else:
          task.status = "failed"
          task.error = "server restarted"
          task.finished_at = _now_iso()
      STATE.persist.save_task(task)
  ```

### 风险 8: peer 代理 + owner 透传

**症状**：peer 节点不知道 proxied 任务的 owner

**回避**：

- peer 模式下 `create_task` 转发时，owner 信息不传给 peer（peer 用自己的 token 鉴权）
- 代理端点 `GET /tasks/{id}` 返回的 owner 是 peer 端的 owner（peer 的 token 对应的 owner）
- 这在多节点多用户场景下语义复杂。本次方案 **简化处理**：peer 模式 + 多用户模式的交集场景不做专门测试，文档注明"peer dispatch 与多用户同时启用时，跨节点任务列表 owner 字段以实际处理节点为准"
- 如需严格一致，后续在 proxy 时透传 owner header，但需要 peer 间互信，本次不做

### 风险 9: 前端任务列表从 localStorage 和服务端列表冲突

**症状**：localStorage 里有旧任务，服务端列表没有，两边不同步

**回避**：

- `refreshFromServer` 后以服务端为准合并：服务端有的更新 localStorage，服务端没有的保留（可能 peer 任务的本地记录）
- 不做"服务端没有就删本地"，避免误删

---

## 附录: 接口契约草案

### Phase A 变更

**§4.4 下载端点加 `?format=`**

```
GET /api/v1/tasks/{task_id}/download?format={md|docx|html|pdf|latex}
```

- 默认 `md`（向后兼容）
- 非 md 格式：服务端调 pandoc 转换，缓存到 `outputs/{task_id}.{ext}`
- DELETE 时清所有格式缓存

### Phase B 变更

**§2 鉴权加多 token 配置文件**

```
~/.ocr_tokens.json:
{
  "tokens": [
    {"token": "t1", "owner": "alice"},
    {"token": "t2", "owner": "bob"}
  ]
}
```

**§3 状态机加 owner 字段**

```
| owner | string | 任务所属用户名（单 token 模式为 "self"）|
```

**新增 §4.6 列表端点**

```
GET /api/v1/tasks?scope=mine|all
→ { "tasks": [...], "count": N, "scope": "mine" }
```

**新增 §4.7 `/me` 端点**

```
GET /api/v1/me
→ { "owner": "alice" }
```

**§6 文件布局加 tasks.db**

```
./api_workdir/
├── ...
└── tasks.db   # sqlite 持久化
```

---

## 完成定义 (Definition of Done)

### Phase A 完成

- [ ] `gateway/convert.py` 实现并通过单元测试
- [ ] `GET /tasks/{id}/download?format=` 5 种格式各返回正确 Content-Type
- [ ] 转换缓存命中验证（第二次同格式请求秒回）
- [ ] DELETE 清所有格式缓存
- [ ] 前端"下载 ▾"下拉菜单 5 选项，各能下载
- [ ] CLI `download --format` 5 种格式
- [ ] peer 代理透传 `?format=`
- [ ] `API_CONTRACT.md` §4.4 更新
- [ ] `README_API.md` 加文档转换章节
- [ ] `Dockerfile` 加 pandoc + libpango
- [ ] `requirements-api.txt` 加 weasyprint
- [ ] A.7 验收脚本全部通过
- [ ] `docs/project_notes/decisions.md` 加 ADR-007, ADR-010, ADR-011
- [ ] `docs/project_notes/issues.md` 记录完成

### Phase B 完成

- [ ] `gateway/users.py` UserRegistry 实现，热加载验证
- [ ] `gateway/auth.py` `get_token` 返回 owner
- [ ] `gateway/state.py` TaskState 加 owner，`_task_to_dict` 输出
- [ ] `GET /api/v1/me` 端点
- [ ] `GET /api/v1/tasks?scope=mine|all` 端点
- [ ] `gateway/persist.py` sqlite 实现
- [ ] worker 状态变更插桩 `persist.save_task`
- [ ] 启动时 `persist.load_all` 恢复
- [ ] 重启时 running 任务正确处理（zip 在则 completed，否则 failed）
- [ ] DELETE 调 `persist.delete_task`
- [ ] 前端 SettingsBar 显示当前用户
- [ ] 前端 TaskCard owner 徽章
- [ ] 前端 TaskList scope 切换 + 服务端刷新
- [ ] CLI `list` `whoami` 子命令
- [ ] `API_CONTRACT.md` §2 §3 §4.6 §4.7 §6 更新
- [ ] `README_API.md` 加多用户配置章节
- [ ] B.9 验收脚本全部通过
- [ ] `docs/project_notes/decisions.md` 加 ADR-008, ADR-009
- [ ] `docs/project_notes/key_facts.md` 加 tasks.db / tokens.json 路径
- [ ] `docs/project_notes/issues.md` 记录完成

---

*本方案基于 2026-06-30 与用户讨论确定。Phase C 知识库导出 hook 明确不做，等后续方向明确后再立方案。*

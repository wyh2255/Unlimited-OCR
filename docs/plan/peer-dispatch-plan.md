---
日期: 2026-06-27
文档类型: 技术方案
文档概述: Unlimited-OCR 对等调度 (Peer Dispatch) 实现方案。双 GPU (A100 40GB + RTX 3090 24GB) 自动调度，互备容错，单机降级。
---

# 对等调度 (Peer Dispatch) 实现方案

## 目录

- [背景与目标](#背景与目标)
- [整体架构](#整体架构)
- [调度逻辑](#调度逻辑)
- [文件变更清单](#文件变更清单)
- [Phase 1: 后端对等调度](#phase-1-后端对等调度)
- [Phase 2: Web 前端多服务器支持](#phase-2-web-前端多服务器支持)
- [Phase 3: 文档与部署指南](#phase-3-文档与部署指南)
- [决策记录](#决策记录)
- [验收标准](#验收标准)

## 背景与目标

**现状**：当前 `gateway/server.py` 是一个单机单 GPU 的 FIFO 服务。前端只能连一台服务器。

**目标**：增加一台 RTX 3090 (24GB) 机器（Windows 10 WSL2），与现有的 A100 (40GB) 服务器组成双节点集群。

- 双节点互相对等，每台都能调度任务到另一台
- A100 是优先连接地址，3090 是备用
- 对等节点离线时自动退化为单机模式（零改动即工作）
- 前端用户无需感知后端有多台机器
- 只需提交一次、一个 URL 即可

## 整体架构

```
        ┌──────────────────────────────────────┐
        │           前端 / CLI                   │
        │   serverUrl: A100 (优先)               │
        │   fallbackUrl: 3090 (备用)             │
        │   (只用自己记得一个地址即可,有备用更好)    │
        └──────────────┬────────────────────────┘
                       │
          ┌────────────┴────────────┐
          │                         │
   ┌──────▼──────┐          ┌──────▼──────┐
   │ A100 gateway │◄──对等──►│ 3090 gateway │
   │ (主调度器)    │  互探健康  │ (副调度器)    │
   │ 40GB VRAM    │          │ 24GB VRAM    │
   │ conc: 8/4/2  │          │ conc: 4/2/1  │
   └──────┬───────┘          └──────┬───────┘
          │                         │
   ┌──────▼───────┐          ┌──────▼───────┐
   │ 本地 SGLang   │          │ 本地 SGLang   │
   │ :10000        │          │ :10000        │
   └───────────────┘          └───────────────┘
```

### 关键原则

1. **对等而非主从** — 两台机器运行完全相同的代码，各自都有自己的 gateway + worker + SGLang
2. **优化转发而非重定向** — 上传到一台机器后，这台机器负责把文件转发给对等节点，客户端只和这一台机器通信
3. **无共享状态** — 每台机器独立管理自己的任务队列、工作目录和日志；仅通过 HTTP 互通
4. **向后兼容** — 旧客户端（无法理解 `peers` 字段的）仍能正常工作

## 调度逻辑

### 上传时调度

```
POST /api/v1/tasks (上传 PDF)
  → 读取 + 校验 PDF (同现有逻辑)
  → probe 所有 --peers 的 /health (超时 3s)
  → 获取 self_health (自己)
  → select_best_backend(self_health, peers_health):
    1. 过滤掉 probe 失败/超时的 peer
    2. 按 current_task == null 排序 (空闲优先)
    3. 按 queue_length 升序
    4. 按 free_mb 降序
    5. 如果自己和对等节点得分相同 → 优先选择 "self"
  → 如果选中 peer:
    → proxy_upload: 原样 multipart POST 到对等节点
    → 存储 STATE.proxied[task_id] = peer_url
    → 返回对等节点的响应 (task_id, status 等)
  → 如果选中 self:
    → 走现有存盘 + 入队逻辑
```

### 任务状态查询/下载/删除

```
GET /api/v1/tasks/{task_id}    (或 download / DELETE)
  → 查 STATE.proxied[task_id]
  → 如果存在 → proxy request 到对应的 peer_url, 直接返回 peer 的响应
  → 如果不存在 → 走本地任务现有逻辑
```

注意：DELETE 时，除了转发到对等节点外，还需清理本地的 `proxied` 映射。

### 健康检查增强

```
GET /api/v1/health (免鉴权)
  → 获取 self_health (自己的 GPU, 队列, 任务)
  → probe 所有 peers 的 /health (超时 3s, 失败则标记 online: false)
  → 合并响应:
    {
      "status": "ok",
      "self": { ... },           // 自己的完整 health
      "peers": {
        "http://peer_url:port": {
          "online": true,
          // peer 的 health 字段
        }
      },
      "best_target": "self" | "http://peer_url:port",
      // --- 向后兼容字段 (deprecated) ---
      "gpu": { "name": "...", ... },
      "concurrency_recommended": 8,
      "queue_length": 0,
      "current_task": null
    }
```

### 单机降级

- 如果在 `main()` 中 `--peers` 未提供或不合法 → `STATE.peers = []`
- 如果上游的所有 pods probe 全部超时 → `peers_health` 为空，自动退化为单机
- 单机模式下所有逻辑与现有代码一致（不需要也无任何新逻辑）

## 文件变更清单

### 后端 (gateway/)

| 文件 | 操作 | 说明 |
|------|------|------|
| `gateway/peers.py` | **新建** | PeerConfig、probe、选路、proxy 工具函数 |
| `gateway/state.py` | 修改 | TaskState 加 backend_url，STATE 加 peers + proxied |
| `gateway/server.py` | 修改 | 新 CLI --peers，上传调度，端点代理，health 扩展 |
| `gateway/concurrency.py` | 修改 | 支持 OCR_CONCURRENCY_TIERS 环境变量覆盖阈值 |
| `gateway/tasks.py` | **不改** | worker 只处理本地任务，无需修改 |
| `gateway/progress.py` | **不改** | poller 只关注本地输出目录，不受影响 |
| `gateway/auth.py` | **不改** | 鉴权方式不变 |
| `gateway/__init__.py` | **不改** | 仅包标记 |

### Web 前端 (clients/web/)

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/types/api.ts` | 修改 | 新增 PeerHealth 类型，扩展 HealthResponse |
| `src/composables/useSettings.ts` | 修改 | 新增 fallbackUrl 字段 |
| `src/composables/useApi.ts` | 修改 | 新增多服务器选择逻辑 |
| `src/composables/useTaskStore.ts` | 修改 | LocalTaskMeta 中加 backend_url |
| `src/components/SettingsBar.vue` | 修改 | 新增备用地址输入 |
| `src/components/UploadPanel.vue` | 修改 | 上传前自动选择空闲服务器 |
| `src/components/HealthBadge.vue` | 修改 | 显示对等节点状态 |
| `src/components/TaskList.vue` | **不改** | 任务列表按 task_id 跟踪，backend_url 在 meta 中自动携带 |
| `src/components/TaskCard.vue` | **不需** | 状态/下载路由到正确 server 由 useApi 处理 |

### 文档

| 文件 | 操作 | 说明 |
|------|------|------|
| `API_CONTRACT.md` | 修改 | health 响应新增 self/peers/best_target 字段 |
| `docs/plan/peer-dispatch-plan.md` | 本文 | 技术方案 |

---

## Phase 1: 后端对等调度

Phase 1 只涉及 `gateway/` 下的 Python 代码。分 4 步。

### 步骤 1.1: 新建 `gateway/peers.py`

```python
from __future__ import annotations

import dataclasses
import requests

@dataclasses.dataclass
class PeerConfig:
    url: str      # 形如 "http://192.168.1.100:10001"
    token: str

def probe_peer(peer: PeerConfig, timeout: float = 3.0) -> dict | None:
    """GET /api/v1/health，成功返回 dict，超时/失败返回 None。"""
    ...

def select_best_backend(self_health: dict, peers_health: dict[str, dict | None]) -> str:
    """返回 "self" 或 peer_url。
    
    选择逻辑:
    1. 从 peers_health 中过滤掉 None (probe 失败的)
    2. 全部候选 (self + 所有可用 peer) 按以下优先级排序:
       a. 空闲 (current_task == null) > 忙碌
       b. queue_length 升序
       c. free_mb 降序
    3. 同分时优先选择 "self"
    """
    ...

def proxy_upload(peer: PeerConfig, content: bytes, image_mode: str, concurrency_hint: int | None) -> requests.Response:
    """将 PDF 内容以 multipart POST 转发到 peer 的 /api/v1/tasks。"""
    ...

def proxy_request(peer: PeerConfig, method: str, path: str) -> requests.Response:
    """通用代理请求: 向 peer 发送 GET/HEAD/DELETE 请求。"""
    ...
```

**注意事项：**
- `requests.session.trust_env = False` (沿用项目默认，避免代理干扰)
- 所有 probe 和 proxy 请求设置 10s 超时
- `select_best_backend` 对 self_health 和 peers_health 使用相同的数据结构

### 步骤 1.2: 修改 `gateway/state.py`

```python
# TaskState 新增字段
@dataclass
class TaskState:
    ...
    backend_url: str = ""  # "" 表示本地任务；非空指向对等节点 URL

# _State 新增字段
class _State:
    ...
    peers: list[PeerConfig] = dataclasses.field(default_factory=list)
    proxied: dict[str, str] = dataclasses.field(default_factory=dict)  # task_id → peer_url
```

`_task_to_dict` 中若 `backend_url` 非空则加入返回字典。

### 步骤 1.3: 修改 `gateway/server.py`

**CLI：**
```python
parser.add_argument("--peers", action="append", default=None,
    help="对等节点 URL 和 token, 格式 'http://host:port,token', 可多次传递")
```

**`main()` 中解析：**
```python
if args.peers:
    for p in args.peers:
        if "," not in p:
            print(f"[server] 警告: 错误格式的 --peers '{p}', 已忽略")
            continue
        url, token = p.rsplit(",", 1)
        STATE.peers.append(PeerConfig(url=url, token=token))
```

**`create_task` (POST /api/v1/tasks) 改造：**

```python
@app.post("/api/v1/tasks", status_code=202, dependencies=[Depends(get_token)])
async def create_task(...):
    # 1. 校验 (现有逻辑保持不变)
    content = await file.read()
    if len(content) > MAX_PDF_BYTES:
        raise HTTPException(status_code=400, detail="PDF exceeds 200 MB")
    if not content.startswith(b"%PDF-"):
        raise HTTPException(status_code=400, detail="uploaded file is not a valid PDF")

    # 2. 对等调度 (新逻辑)
    if STATE.peers:
        self_health = await _get_health_dict()  # 获取自身 health
        peers_health = _probe_peers()
        best = select_best_backend(self_health, peers_health)
    else:
        best = "self"

    if best != "self":
        # 转发到对等节点
        resp = proxy_upload(best_peer, content, image_mode, concurrency_hint)
        if resp.status_code == 202:
            data = resp.json()
            with STATE.lock:
                STATE.proxied[data["task_id"]] = best_peer.url
            return data  # 透传对等节点的响应
        else:
            raise HTTPException(status_code=502, detail=f"peer forward failed: {resp.text}")

    # 3. 本地处理 (现有逻辑)
    task_id = uuid.uuid4().hex[:12]
    ...
```

**`get_task` / `download_task` / `delete_task` 改造：**

```python
def _get_backend_for_task(task_id: str) -> str | None:
    with STATE.lock:
        return STATE.proxied.get(task_id)

# 三个端点统一模式:
@app.get("/api/v1/tasks/{task_id}")
def get_task(task_id: str):
    peer_url = _get_backend_for_task(task_id)
    if peer_url:
        peer = _find_peer(peer_url)
        resp = proxy_request(peer, "GET", f"/api/v1/tasks/{task_id}")
        return resp.json()
    # 现有本地逻辑
    ...
```

**`health` 改造：**

```python
@app.get("/api/v1/health")
def health():
    self_h = _build_self_health()
    peers_h = _probe_peers()
    best_target = select_best_backend(self_h, peers_h)
    
    return {
        "status": "ok",
        "self": {**self_h, "name": gpu_info["name"]},
        "peers": {
            p.url: peers_h.get(p.url, {"online": False})
            for p in STATE.peers
        },
        "best_target": best_target,
        # 向后兼容
        "gpu": gpu_info,
        "concurrency_recommended": self_h["concurrency_recommended"],
        "queue_length": self_h["queue_length"],
        "current_task": self_h["current_task"],
    }
```

### 步骤 1.4: 修改 `gateway/concurrency.py`

```python
def detect_concurrency(gpu_index: int = 0) -> int:
    free_gb = _get_free_gb(gpu_index)
    
    # 从环境变量 OCR_CONCURRENCY_TIERS 读取自定义阈值
    # 格式: "free_gb_threshold:concurrency,free_gb_threshold:concurrency,..."
    # 例如: "16:4,6:2,0:1" 表示 ≥16GB→4, ≥6GB→2, 否则→1
    tiers_env = os.environ.get("OCR_CONCURRENCY_TIERS", "")
    if tiers_env:
        try:
            tiers = [(float(t), int(c)) for t, c in (p.split(":") for p in tiers_env.split(","))]
            tiers.sort(reverse=True)
            for threshold, conc in tiers:
                if free_gb >= threshold:
                    return conc
        except (ValueError, AttributeError):
            pass  # 格式错误时回退默认
    
    # 默认阈值 (A100 优化)
    if free_gb >= 30.0:
        return 8
    if free_gb >= 10.0:
        return 4
    return 2
```

---

## Phase 2: Web 前端多服务器支持

### 步骤 2.1: 修改 `types/api.ts`

```typescript
export interface PeerHealth {
  online: boolean;
  name: string;
  free_mb: number;
  concurrency_recommended: number;
  queue_length: number;
  current_task: string | null;
}

export interface HealthResponse {
  status: 'ok';
  self: GpuInfo & { concurrency_recommended: number; queue_length: number; current_task: string | null };
  peers: Record<string, PeerHealth | null>;
  best_target: string;
  // 向后兼容
  gpu: GpuInfo;
  concurrency_recommended: number;
  queue_length: number;
  current_task: string | null;
}

export interface LocalTaskMeta {
  task_id: string;
  file_name: string;
  file_size: number;
  image_mode: ImageMode;
  concurrency_hint: number | null;
  created_local: string;
  last_seen_status: TaskStatus | null;
  last_polled: string | null;
  backend_url: string;  // 新增: 记录提交到了哪个服务器
}
```

### 步骤 2.2: 修改 `useSettings.ts`

```typescript
export interface AppSettings {
  serverUrl: string;
  fallbackUrl: string;   // 新增
  token: string;
  autoWatch: boolean;
}

const DEFAULT_SETTINGS: AppSettings = {
  serverUrl: 'http://127.0.0.1:10001',
  fallbackUrl: '',        // 可空
  token: '',
  autoWatch: true,
};
```

### 步骤 2.3: 修改 `useApi.ts`

```typescript
// 新增 MultiServerApiClient
export class MultiServerApiClient {
  private primary: ApiClient;
  private fallback: ApiClient | null;
  private taskBackend: Map<string, string>; // task_id → server url

  constructor(primaryUrl: string, fallbackUrl: string, token: string) {
    this.primary = new ApiClient(primaryUrl, token);
    this.fallback = fallbackUrl ? new ApiClient(fallbackUrl, token) : null;
    this.taskBackend = new Map();
  }

  // 上传: 选空闲服务器
  async upload(opts: UploadOptions): Promise<UploadResponse> {
    const servers = [this.primary, ...(this.fallback ? [this.fallback] : [])];
    // 并行 probe /health
    const results = await Promise.allSettled(
      servers.map(s => s.health())
    );
    // 选空闲的 (current_task === null && queue_length === 0)
    // 都没有空闲则选 queue_length 最短的
    // 同分选 primary
    const chosen = this._pickBest(results, servers);
    const resp = await chosen.upload(opts);
    this.taskBackend.set(resp.task_id, chosen === this.primary ? settings.value.serverUrl : settings.value.fallbackUrl);
    return resp;
  }

  // status/download/delete: 按 task 记录的 backend
  getTask(taskId: string): Promise<TaskInfo> {
    return this._getClient(taskId).getTask(taskId);
  }
  downloadResult(taskId: string, fileName: string): Promise<void> {
    return this._getClient(taskId).downloadResult(taskId, fileName);
  }
  deleteTask(taskId: string): Promise<void> {
    return this._getClient(taskId).deleteTask(taskId);
  }
  fetchResultBlob(taskId: string): Promise<Blob> {
    return this._getClient(taskId).fetchResultBlob(taskId);
  }

  private _getClient(taskId: string): ApiClient {
    const url = this.taskBackend.get(taskId);
    if (url === settings.value.fallbackUrl && this.fallback) return this.fallback;
    return this.primary;
  }
}
```

### 步骤 2.4: 修改 `SettingsBar.vue`

在编辑面板中新增一个输入框：
```html
<div class="topbar__form-row">
  <span class="label">Fallback URL</span>
  <input v-model="draftFallback" class="input"
         placeholder="http://192.168.1.100:10001 (可空)"
         @keyup.enter="save" />
</div>
```

### 步骤 2.5: 修改 `UploadPanel.vue`

```typescript
// computed api 改为使用多服务器客户端
const api = computed(() => new MultiServerApiClient(
  settings.value.serverUrl,
  settings.value.fallbackUrl,
  settings.value.token,
));
// upload 后保存 backend_url 到 taskStore
```

### 步骤 2.6: 修改 `HealthBadge.vue`

当前只显示单机的 GPU 信息。修改为：

```html
<div v-if="peers && Object.keys(peers).length">
  <div v-for="(info, url) in peers" :key="url">
    {{ info.online ? '🟢' : '🔴' }} {{ info.name }}
    · {{ formatMb(info.free_mb) }} 空闲
  </div>
</div>
<div class="self-info">
  🖥️ {{ self.name }} · {{ formatMb(self.free_mb) }} 空闲
</div>
```

---

## Phase 3: 文档与部署指南

### 步骤 3.1: 更新 `API_CONTRACT.md`

在 §4.1 `GET /api/v1/health` 中新增 `self` / `peers` / `best_target` 字段说明，
并将旧字段 `gpu` / `concurrency_recommended` / `queue_length` / `current_task` 标记为 deprecated。

### 步骤 3.2: 更新项目记忆

在 `docs/project_notes/issues.md` 中记录 Phase 1~3 的状态。
在 `docs/project_notes/decisions.md` 中新增 ADR-006 记录对等调度决策。

### 步骤 3.3: 更新 AGENTS.md

在适当位置添加对等调度的说明和已知陷阱。

### 步骤 3.4: 输出 3090 WSL2 部署指南

```bash
# === Windows 10 端操作 ===

# 1. 启用 WSL2 + 安装 Ubuntu 24.04 LTS
wsl --install -d Ubuntu-24.04

# 2. 在 WSL2 内安装 CUDA (WSL2 专用版)
wget https://developer.download.nvidia.com/compute/cuda/repos/wsl-ubuntu/x86_64/cuda-keyring_1.1-1_all.deb
sudo dpkg -i cuda-keyring_1.1-1_all.deb
sudo apt update
sudo apt install -y cuda-toolkit-12-6

# 3. 安装 Python 和 uv
sudo apt install -y python3.12 python3.12-venv curl
curl -LsSf https://astral.sh/uv/install.sh | sh

# 4. 克隆仓库
git clone <repo-url> ~/Unlimited-OCR
cd ~/Unlimited-OCR

# 5. 创建 venv 并安装依赖
uv venv --python 3.12
source .venv/bin/activate
uv pip install wheel/sglang-0.0.0.dev11416+g92e8bb79e-py3-none-any.whl
uv pip install kernels==0.11.7 pymupdf==1.27.2.2
uv pip install -r requirements-api.txt
uv pip install ninja

# 6. 拷贝模型权重 (从 A100 服务器)
rsync -avz user@<A100_IP>:/path/Unlimited-OCR/Unlimited-OCR/ ./Unlimited-OCR/

# 7. 启动 (使用 3090 专用并发阈值 + 对等调度)
export OCR_API_TOKEN="<与 A100 相同的 token>"
export OCR_CONCURRENCY_TIERS="16:4,6:2,0:1"
python -m gateway.server \
    --host 0.0.0.0 \
    --port 10001 \
    --gpu 0 \
    --model-dir ./Unlimited-OCR \
    --workdir ./api_workdir \
    --peers "http://<A100_IP>:10001,<token>"

# 8. Windows 防火墙 + 端口转发 (PowerShell 管理员)
$wsl_ip = (wsl hostname -I).Trim().Split()[0]
netsh interface portproxy add v4tov4 listenport=10001 listenaddress=0.0.0.0 connectaddress=$wsl_ip connectport=10001
```

---

## 决策记录

### ADR-006: 对等调度 (Peer Dispatch) 架构 (2026-06-27)

**背景：**
- 需要利用第二块 GPU (RTX 3090) 在另一台机器上分担 OCR 工作负载
- 当一台机器不可用时，系统必须能继续工作（单机降级）
- 用户只需要知道一个 URL

**决策：**
- 双节点对等架构，每台机器独立运行完整的 gateway + worker + SGLang
- 上传时通过 HTTP 探测对等节点健康，根据空闲程度调度
- 被调度到对等节点的任务通过透明代理转发状态/下载/删除请求
- 无需共享存储、无需消息队列、无需额外基础设施

**替代方案：**
- 主从架构（A100 作为调度器，3090 只做 worker）→ 单点故障，A100 挂了全系统不可用
- 前端 DNS 轮询 → 无法感知后端负载，可能把任务发给正在忙的节点
- 消息队列 (Redis/Celery) → 增加基础设施复杂度，不符合"无外部依赖"的设计

**后果：**
- A100 增加少量额外负担（探测 + 转发 PDF），通常 <1s
- 前端需要感知多服务器地址（主 + 备用），但只用一个地址也可工作
- 对等节点的 PDF 内容经过内存中转（最大 200 MB），LAN 内可忽略
- 任务状态完全在提交的机器上维护，对等节点重启不影响已提交的任务记录

---

## 验收标准

1. **Unit**: `select_best_backend()` 在各种场景下返回正确结果
2. **Unit**: `probe_peer()` 成功/失败/超时三种情况
3. **Integration**: 两个 gateway 实例在同一台机器上启动（不同端口），验证:
   - 上传 → 自动调度到空闲节点
   - 状态查询代理正常工作
   - 下载代理正常工作
   - 删除代理正常工作
   - health 报告对方状态
4. **Integration**: 停掉其中一个 gateway，验证单机降级
5. **E2E**: 前端同时配置主/备用地址，上传 PDF 后自动调度到空闲服务器

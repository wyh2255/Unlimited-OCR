# Architectural Decision Records (ADRs)

Lightweight ADRs for this repo. Newest first; older entries kept for context.

---

### ADR-007: Peer 健康探测改用后台缓存而非同步阻塞 (2026-06-27)

**Context:**
- 双 Gateway 互指 `--peers` 时，A 的 `/health` 会同步探测 B，B 的 `/health` 又探测 A
- 形成递归调用链：A→B→A→B... 每个请求阻塞等待响应
- WSL2 环境下 http_proxy 导致本地请求也有 ~5s 延迟
- 合成效果：一次 health 请求耗时 6-8s，peers 仍显示 `online: false`

**Decision:**
- 新增后台守护线程 `_update_peer_cache()`，每 15s 探测所有 peers
- `_probe_peers()` 改为读取缓存，不阻塞 health 响应
- `_State.peer_cache` + `_State.peer_cache_lock` 存储缓存
- 启动时调用 `_initial_peer_cache_sync()` 填充初始缓存
- 单次 probe 超时 5s（原 3s），给首次连接足够时间

**Alternatives Considered:**
- 同步探测 + 短超时（1s）→ 每次 health 都报 peer offline，前端看不到真实状态
- 移除 peer 探测 → `best_target` 永远返回 self，peer dispatch 变单机
- `asyncio.to_thread` + 超时 → 仍可能阻塞线程池，且 uvicorn sync handler 配合复杂

**Consequences:**
- health 响应从 6-8s 降至 ~0.18s（仅 nvidia-smi 查询时间）
- peers 状态最多 15s 延迟（后台轮询间隔），对上传调度足够
- 启动时增加 ~5-10s 初始化延迟（同步探测所有 peers）
- 新增内存开销：peer_cache 字典（< 1 KB 每 peer）

---

### ADR-006: Peer Dispatch 对等调度架构 (2026-06-27)

**Context:**
- 需要利用第二块 GPU（RTX 3090 24GB，Windows 10 WSL2）分担 OCR 负载
- 当一台机器不可用（关机/网络中断）时系统必须能继续工作
- 前端用户只需要知道一个 URL

**Decision:**
- 双节点对等架构：每台机器运行完整 gateway + worker + SGLang
- 上传时通过 HTTP 探测对等节点 `/health`，根据空闲程度调度
- 被调度到对等节点的任务通过透明代理转发状态/下载/删除请求
- 无需共享存储、无需消息队列、无需额外基础设施
- A100 是默认优先连接的地址，3090 是备用

**Alternatives Considered:**
- 主从架构（A100 调度，3090 只做 worker）→ A100 挂了整个系统不可用
- 前端 DNS 轮询 → 无法感知后端负载，可能把任务发给正在忙的节点
- Redis/Celery 消息队列 → 增加基础设施复杂度，违反"无外部依赖"设计原则

**Consequences:**
- A100 增加少量额外负担（探测 + 转发 PDF），LAN 内可忽略 (<1s)
- PDF 内容经过内存中转（最大 200 MB），LAN 内足够快
- 对等节点重启不影响已提交的任务记录（任务状态在提交的机器上维护）
- 向后兼容：旧客户端看到的 health 字段不变，仅新增 `self`/`peers`/`best_target`

---

### ADR-005: Split web frontend into scaffold + components commits (2026-06-26)

**Context:**
The first attempt at the web frontend landed in a single 27-file, 3800-line
commit. Reviewing it required holding the whole Vite scaffold, the design
tokens, the data layer, and eight Vue components in head at once. Bisecting
later required checking out the entire frontend.

**Decision:**
Two commits for the web layer (at the time located at `web/`, since moved
to `clients/web/` in the Phase 1-5 reorganization):
1. **Scaffold** — Vite/Vue 3/TS config, design tokens, types, composables,
   `main.ts`, `index.html`, `package.json`, `pnpm-lock.yaml`, `.gitignore`.
2. **Components** — `App.vue` and the 8 component files plus `README.md`.

**Alternatives Considered:**
- Single commit (the original) → hard to review, hard to bisect.
- Per-component commits (10 commits) → too granular; common changes
  (e.g. token storage format) span components.
- Scaffold + per-feature-component commits (5+ commits) → better for
  long-running feature work, but the frontend is small enough that 2 layers
  are enough.

**Consequences:**
- Reviewing the data layer (composables) is one commit, separate from the UI.
- Reverting just the UI or just the scaffold is now possible.
- Each commit still leaves the project in a buildable state on its own
  (scaffold commit only lacks `App.vue` → blank page; components commit
  restores the full app).
- AGENTS.md "Web Frontend" section structure now mirrors the commit order,
  making it easier to find which file lives in which layer.

---

### ADR-004: Use fflate (not JSZip) for in-browser ZIP extraction (2026-06-26)

**Context:**
`ResultViewer.vue` (currently at `clients/web/src/components/ResultViewer.vue`)
needs to read `result.md` and the `images/` directory out of the per-task
result ZIP, in the browser, with no server staging. Bundling a ZIP library
is unavoidable.

**Decision:**
`fflate` 0.8.x — ~9 KB minified, sync `unzipSync(uint8Array)`, no Promises,
works in every modern browser. Pairs with `new Blob([uint8Array], {type})`
for image previews.

**Alternatives Considered:**
- `jszip` → larger (~100 KB), async-only API, heavier.
- Hand-rolled with `DecompressionStream('deflate-raw')` → first attempt,
  failed because ZIP is a container with per-entry deflate, not a single
  stream. Logged in `bugs.md`.
- Server-side staging (upload ZIP to a public URL) → defeats the point of
  in-browser preview and would need cleanup logic.

**Consequences:**
- +9 KB to the production bundle (79 KB gz total, well under any budget).
- Sync API keeps the `ResultViewer` loader logic linear instead of nested
  promise chains.
- No streaming for very large ZIPs (sync decode on the main thread); for
  the 50–800 KB result ZIPs this project produces, that's fine. If a
  future use-case lands multi-megabyte result ZIPs, revisit.

---

### ADR-003: Vite `@/` alias in both `tsconfig.json` and `vite.config.ts` (2026-06-26)

**Context:**
The frontend uses `@/composables/...` and `@/types/...` imports throughout
to avoid `../../composables/...` chains. Naively this works in the editor
via `tsconfig.json paths` but not at build time. Files are at
`clients/web/tsconfig.json` and `clients/web/vite.config.ts`.

**Decision:**
Configure the `@/` alias in **both** places, kept in sync:
- `clients/web/tsconfig.json` `compilerOptions.paths` (and `baseUrl`) —
  for `vue-tsc`, IDE intellisense.
- `clients/web/vite.config.ts` `resolve.alias` — for Rollup at build/dev time.

**Alternatives Considered:**
- Relative imports only → verbose, no win.
- Only `tsconfig.json` → first try, build broke. Logged in `bugs.md`.
- Only `vite.config.ts` → editor shows red squigglies.

**Consequences:**
- Adding a new alias requires editing both files. A reviewer who catches
  one and not the other will see a confusing failure.
- Pattern is the same as a typical Vue 3 + Vite starter, so anyone who
  has used Vite before will recognize it.

---

### ADR-002: Add CORS middleware to the gateway (2026-06-26)

**Context:**
A browser frontend on a different origin (`:5173`) cannot call the LAN
gateway (`:10001`) without a CORS opt-in from the server. The original
LAN gateway (then `server.py`, now `gateway/server.py`) had no CORS
configuration.

**Decision:**
Install `fastapi.middleware.cors.CORSMiddleware` with a `--cors-origin`
CLI flag (repeatable, default `['*']` for LAN). Expose
`Content-Disposition` so the browser can read the suggested ZIP filename
on download. Configuration is performed through a `configure_cors(origins)`
helper called from `main()`, not via `app.add_middleware()` at module
import, because the latter is silently ignored once the middleware stack
is built. See `bugs.md` for the chain of debugging. (Phase 4 on `main`
later moved the middleware to module-level, which is the cleaner final
form — `configure_cors` is now mostly a no-op; see that commit for
context.)

**Alternatives Considered:**
- Run the frontend through a reverse proxy on the same origin → adds
  deployment complexity, breaks the "no extra infra" pitch.
- Open CORS to `*` only → that is the current default (`'*'`), but
  production deployments can tighten via `--cors-origin http://...:5173`.
- Disable CORS via a browser flag for development → brittle, doesn't
  match how end users will run it.

**Consequences:**
- Server still has no authentication on its CORS responses (no
  `allow_credentials=True` problem since Bearer is in `Authorization`,
  not cookies).
- A misconfigured `--cors-origin` silently produces a broken browser
  client. The Startup Runbook's pre-flight checklist now calls this out.
- Same-origin `curl` and `clients/python-cli/` users are unaffected.

---

### ADR-001: Add a browser frontend (Vue 3 + Vite + TS) for the LAN service (2026-06-26)

**Context:**
`clients/python-cli/` (the packaged CLI, originally a root-level `client.py`)
works but requires terminal access on every laptop and offers no in-line
preview. The result ZIP is downloaded and unzipped manually. For occasional
users, a web UI is friendlier.

**Decision:**
Vue 3 (Composition API + `<script setup>`) + TypeScript + Vite 6 SPA in
`web/` (since moved to `clients/web/` in the Phase 1-5 reorganization).
No backend changes beyond the CORS middleware (ADR-002). Production
build: 79 KB gz JS / 4 KB gz CSS. Token + server URL persisted to
`localStorage`. Three tabs: 上传 / 任务列表 / 结果预览.

**Alternatives Considered:**
- React 18 → equally capable, larger ecosystem; team preference for Vue
  due to existing familiarity.
- Svelte 5 → smallest bundle, but smaller ecosystem and unfamiliar to
  the team.
- Single-file HTML with no build step → no TypeScript, no `marked`,
  no `fflate` without manual vendoring. Rejected because the resulting
  bundle would be larger than the current Vue build.
- Server-rendered with FastAPI templates → couples rendering to the
  server; loses the SPA benefits (live polling, instant tab switch,
  in-place settings).

**Consequences:**
- +79 KB gz JS per page load (acceptable on a LAN).
- Hard dependency on CORS being enabled on the server (ADR-002). If
  CORS is removed, the frontend breaks.
- Local-only state for task metadata in `localStorage`. Tasks whose
  state the server has forgotten (e.g. after a restart) show as
  `failed (404)` and can be deleted locally.
- The `clients/web/` directory has its own `.gitignore` and
  `package.json`; the Python project does not need any frontend-aware
  tooling.

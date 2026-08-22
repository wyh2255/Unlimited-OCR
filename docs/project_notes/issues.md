# Work Log

Date-ordered log of completed work. Newest first. Each entry should be 1–3
lines plus links / notes.

## 2026-08-22

### 一键部署体系：脚本整理 + README/AGENTS 部署手册

- **Status**: 完成
- **操作**:
  - 重写 `start_server.sh`（幂等后台启动：health 探测 + pidfile + 就绪等待）、`start_gateway.sh`
    （前台调试，去掉硬编码 /root 路径与固定 token）
  - 新增 `stop_server.sh`（pidfile SIGTERM → 15s 后 SIGKILL）与 `scripts/setup_env.sh`
    （首次部署：apt 系统包 → uv venv → 定制 wheel + requirements-api.txt → HF 模型下载 → import 验证）
  - README.md 新增「一键部署」章节（要求→安装→启动→验证→客户端→FAQ→环境变量表）；
    AGENTS.md Startup Runbook 全量改写为一键脚本路径，保留手动方式备查
  - 本机验证：start（health ok / 401 鉴权 ok）→ 幂等重入 → stop 全链路通过
- **坑**: 初版用 `setsid nohup ... &` 导致 `$!` 记录的是已退出的 setsid 父 PID，
  pidfile 失效；且本机无 ss/netstat/lsof，端口检查静默通过。改为裸 nohup+disown +
  curl health 探测。见 bugs.md 2026-08-22。

## 2026-07-26

### 环境搭建 + SGLang 端到端测试 + LAN 网关部署 (RTX 4090)

- **Status**: 完成
- **操作**:
  - 创建 `.venv` (uv venv --python 3.12)
  - 安装 sglang 定制 wheel + kernels 0.11.7 + pymupdf 1.27.2.2
  - 安装 API 依赖 (requirements-api.txt)
  - 修复问题: `libnuma.so.1` 缺失 → `apt install libnuma-dev`
  - 修复问题: `SGL_KERNEL_ARCH=90` 环境变量 (sgl_kernel 只有 sm90/sm100 变体, RTX 4090 是 sm89)
  - 修复问题: `g++` 缺失 → `apt install g++`
  - 修复问题: `is_torch_fx_available` 在 transformers 5.3.0 不存在 → 修改模型代码添加兼容 fallback
  - 修复问题: flash_attn 命名空间包缺少 `flash_attn_func` → 修改模型代码, import 失败时静默跳过
  - 安装缺失依赖: `addict`, `matplotlib`, `easydict`
  - SGLang 批量推理测试: 14 页 PDF, 196.67 TPS, 68s wall time, 全部通过
  - postprocess 测试: 生成 result.md + 图片目录
  - LAN 网关部署: port 10001, CORS `*`, 全链路验证通过 (上传→推理→下载→删除)
- **bugs.md**: 更新 07-26 条目 (sgl_kernel 架构、g++ 缺失、flash_attn 命名空间包)
- **key_facts.md**: 更新启动命令速查

## 2026-07-01

### Live 烟雾测试：ninja PATH 修复 + 14 页 PDF 解析成功

- **Status**: 通过
- **测试内容**:
  - 上传 14 页论文 PDF（`Unlimited-OCR.pdf`，450 KB）→ 全部 14 页解析完成
  - 结果：41 KB `result.md` + 3 张 figure 图片（总计 407 KB ZIP）
  - 轮询 ~100s 完成任务（20 poll × 5s），无报错
- **发现并修复**:
  - ninja PATH 问题复发（第三次），本次从代码层根治：
    在 `inference/batch.py:start_server()` 中显式将 `.venv/bin` 注入 env PATH
  - 旧方案（文档提醒 + 启动加 PATH）仅运维层防护，SGLang 内部进程树
    （`multiprocessing.set_executable` + `numactl` + `tvm_ffi`）会使 PATH 丢失
  - 代码层 fix 后不再依赖启动方式
- **bugs.md**: 更新 07-01 条目（根因 + 代码 fix），交叉引用旧 06-26 条目
- **key_facts.md**: 新增启动命令速查 & venv PATH 注意事项（之前 session 更新）

### Phase A+B 合并到 A100-server + 项目状态总结

- **Status**: 完成
- **操作**:
  - 从 `feature/doc-conversion-and-multiuser` cherry-pick 4 个功能提交到 `A100-server`
  - 无冲突，已推送远程
- **当前里程碑**:

| 阶段 | 状态 |
|------|------|
| Phase 1-5（代码重组） | ✅ |
| 基线（SGLang + FastAPI） | ✅ |
| Web 前端（Vue 3） | ✅ |
| Peer Dispatch（双 GPU） | ✅ |
| Phase A（文档转换） | ✅ |
| Phase B（多用户 + 持久化） | ✅ |
| Phase C（知识库导出） | ⏸ 已搁置 |
| CI/CD | ❌ |
| main 合并 | ❌ |

- **CLI 分发方案确定**: GitHub 直装 (`pip install git+https://...#subdirectory=clients/python-cli`)，wheel download 端点为辅助方案
- **项目全貌**: PDF 上传 → 5 种格式下载，多用户/多 GPU/Web+CLI 双端，缺测试和发布流程

## 2026-06-30

### Phase A + B (document conversion + multi-user) — implementation complete

- **Status**: Phase A Done · Phase B Done · Phase C deferred (per decision)
- **Branch**: `feature/doc-conversion-and-multiuser` (6 commits, off `A100-server`)
- **Plan**: `docs/plan/doc-conversion-and-multiuser-plan.md`

- **Phase A — document conversion (pandoc + weasyprint)**:
  - `gateway/convert.py`: pandoc wrapper, 5 formats (md/docx/html/pdf/latex),
    auto-detects pandoc version for `--embed-resources` (≥2.19) vs
    `--self-contained` (older); `--standalone` for latex/pdf; 180s timeout
  - `gateway/server.py`: download endpoint `?format=` param (default md,
    backward compat); conversion cache at `outputs/{id}.{ext}`; DELETE clears
    caches; `--pandoc-pdf-engine` CLI flag (default weasyprint)
  - Frontend: ResultViewer dropdown menu (5 formats); useApi.downloadAs()
  - CLI: `download --format md|docx|html|pdf|latex`
  - Docs: API_CONTRACT v1.2, README_API 文档转换输出 section, Dockerfile
    +pandoc/libpango/fonts-noto-cjk, requirements-api +weasyprint
  - ADR-007 (weasyprint), ADR-008 (server-side convert), ADR-009 (md default)
  - E2E verified: all 5 formats return correct Content-Type + magic bytes;
    cache hit 0.008s; DELETE cleans all caches

- **Phase B — multi-user + sqlite persistence**:
  - `gateway/users.py`: UserRegistry — token→owner from `~/.ocr_tokens.json`,
    mtime hot-reload, single-token fallback (owner="self")
  - `gateway/persist.py`: SQLite `tasks.db` (stdlib sqlite3); save/load/delete
  - `gateway/auth.py`: get_token returns owner (not raw token)
  - `gateway/state.py`: TaskState +owner +pdf_name; _task_to_dict outputs both
  - `gateway/server.py`: create_task writes owner; `GET /me`; `GET /tasks?scope=`;
    `--tokens-file` CLI; main() configures users + persists + recovers on startup
    (running→completed if zip exists else→failed); DELETE clears sqlite row
  - `gateway/tasks.py`: _persist() at every state transition
  - Frontend: SettingsBar shows current user; TaskCard owner badge; TaskList
    scope toggle + server refresh; useApi.whoami()/listTasks()
  - CLI: `whoami` + `list [--scope mine|all] [--limit N]` (rich table)
  - Docs: API_CONTRACT v1.3, README_API 多用户配置 section, ADR-010
    (multi-token+sqlite), ADR-011 (no KB hook), key_facts updated
  - E2E verified: /me, scope filtering, hot reload, single-token fallback,
    sqlite recovery, delete clears row; live server + CLI whoami/list tested

- **Phase C — knowledge base export hook**: not implemented (per ADR-011;
  direction RAG vs wiki vs Obsidian undecided)

- **Coordination notes**:
  - 1 subagent returned empty (no changes) on first Phase A backend attempt;
    coordinator did backend directly. Subsequent subagent calls succeeded.
  - pandoc 2.12 (conda) on dev host; symlinked to .venv/bin/pandoc so it's
    on PATH without shadowing venv python. `--embed-resources` not in 2.12
    → version detection in convert.py handles both old and new pandoc.
  - Found + fixed: _task_to_dict didn't output pdf_name (persisted but not
    in API response); CLI list pdf_name column was empty until fix.
  - Pre-existing ruff F401 (Header unused in server.py) left alone.

### Phase A + B — live startup demo (real A100, no mocks)

- **Status**: 11/11 functional tests passed on real hardware
- **Setup**: 3-user tokens.json (alice/bob/carol), pre-seeded
  `DEMO000000001` (alice, completed, 8 pages, LEMMA_paper.pdf) with real
  result.md + 2 images in zip + sqlite row. Server on :10001.
- **Results**:
  1. `/health` → A100 40GB free, concurrency_recommended=8 ✓
  2. `/me` → alice/bob/carol return correct owner; wrong/no token → 401 ✓
  3. Task list scope filtering → alice sees 1, bob sees 0, all sees 1 ✓
  4. 5-format download → md/docx/html/pdf/latex all HTTP 200, correct
     Content-Type + magic bytes (PK/<!DO/%PDF/%) ✓
  5. Conversion cache hit → docx 2nd request 0.025s (first ~1s) ✓
  6. File content quality → PDF: Chinese + LEMMA + table render correctly;
     DOCX: 31 paragraphs, 2 embedded images; HTML: 2 base64 images + table;
     LaTeX: full `\documentclass` ✓
  7. CLI `whoami` + `list` → rich table with owner/pdf_name columns ✓
  8. CLI `download --format` × 5 → all succeed, md auto-extracts ✓
  9. Persistence restart → kill server, restart, `recovered 1 tasks`,
     task list + download still work ✓
  10. Hot reload → add dave/remove bob in tokens.json, no restart, dave
      works immediately, bob revoked immediately ✓
  11. DELETE → clears zip + 4 format caches + sqlite row, list → 0 ✓
- **Bugs found during demo**: none (all 3 known bugs already fixed in code
  before demo: pandoc version flag, persist circular import, pdf_name
  missing from API response).
- **Cleanup**: demo tokens.json + DEMO task removed after demo.

## 2026-06-27

### Peer dispatch — implementation complete

- **Status**: Phase 1 Done · Phase 2 Done · Phase 3 Done
- **Description**: Three subagents implemented the full peer dispatch:
  - **Phase 1-A**: `gateway/peers.py` (PeerConfig, probe, select, proxy),
    `gateway/state.py` (+backend_url, +peers, +proxied),
    `gateway/concurrency.py` (+OCR_CONCURRENCY_TIERS env var)
  - **Phase 1-B**: `gateway/server.py` (+--peers CLI, upload dispatch,
     endpoint proxy for GET/DELETE/download, enhanced health with self/peers)
  - **Phase 2**: Web frontend multi-server support (MultiServerApiClient,
     fallback URL in settings, health badge peer display, upload router)
- **Notes**: All Python imports pass, all TS typechecks pass. 2 pre-existing
  ruff warnings (Header, _now_iso — not from this change). Plan at
  `docs/plan/peer-dispatch-plan.md`. ADR-006 in decisions.md.
  Pushed to remote: commit `9aeea9a` on `feature/web-frontend`.
  Deployment guide at `docs/3090-wsl2-deployment-guide.md`.

## 2026-06-26

### Web frontend feature merged into `feature/web-frontend`

- **Status**: Completed
- **Description**: 4 sequential commits add CORS middleware to the LAN
  gateway and a Vue 3 + Vite + TS browser frontend (then `web/`, now
  `clients/web/`).
- **Notes**: Commits (oldest first):
  `c79996f` initial LAN service files, `ee7bdcb` CORS middleware,
  `84a6c69` web scaffold, `7695f6f` web components.
  Production bundle: 79 KB gz JS / 4 KB gz CSS.
  See ADR-001 to ADR-005 in `decisions.md`.

### E2E closeout (Round 3, browser path)

- **Status**: Completed
- **Description**: 7-page Benchmarking PDF → 152 s wall, 9 images, 338-line
  result.md, full lifecycle (upload / poll / download / 204 delete) green.
  8-page LEMMA PDF via Node `fetch` (mimics browser Origin + Authorization
  + preflight) → 165 s wall, 783 KB ZIP, all 7 contract assertions passed.
- **Notes**: Chromium `--headless --dump-dom` shows Vue mounted and all
  three tabs present. Production build serves via `vite preview`.
  See `AGENTS.md` Test/Build Logbook "Round 3".

### Branch reorganized into 4 commits

- **Status**: Completed
- **Description**: Soft-reset the original single 27-file commit and re-landed
  as 4 sequential commits: initial LAN service, CORS, web scaffold, web
  components. Verified each commit is independently buildable.
- **Notes**: The CORS additions to `gateway/server.py` (then `server.py`)
  were temporarily stripped for the "initial LAN service" commit, then
  re-added in the CORS commit. Same code, cleaner history.

### AGENTS.md updated for the web frontend

- **Status**: Completed
- **Description**: Added `## Web Frontend` section, Round 3 to the
  logbook, Pitfalls #14 (ninja) and #15 (CORS middleware setup), and the
  Startup Runbook's Web Frontend subsection + ninja pre-flight checks.
- **Notes**: 339 → 467 lines.

### Bugs found and fixed during the e2e

- **Status**: Completed
- **Description**: Three bugs surfaced and were fixed (or had the
  workaround documented): ninja not on PATH, hand-rolled ZIP inflate,
  Vite alias only in tsconfig. One (CORSMiddleware silently ignored) led
  to a helper that does clear → reset → re-add.
- **Notes**: All four entries in `bugs.md`.

### CORS preflight verified end-to-end

- **Status**: Completed
- **Description**: `OPTIONS /api/v1/tasks` with
  `Origin: http://127.0.0.1:5173` and `Access-Control-Request-Headers:
  authorization` returns 200 with the correct
  `access-control-allow-origin`, `allow-headers`, `allow-methods`, and
  `expose-headers: Content-Disposition`.
- **Notes**: Same check via `curl` and via Node `fetch`; identical
  response. Browser path therefore does not need a separate preflight
  exception.

### `.gitignore` extended

- **Status**: Completed
- **Description**: Added patterns for `Unlimited-OCR/` (6.4 GB model
  weights), `*.pdf` (sample inputs), `outputs_clean/`, `ocr_output_*/`,
  `ocr-client/` (separate project), and `f[0-9a-f]*.zip` (test artifacts
  that get downloaded as `<task_id>.zip`).
- **Notes**: No existing tracked file was affected; the new patterns only
  apply to the working tree.

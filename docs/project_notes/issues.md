# Work Log

Date-ordered log of completed work. Newest first. Each entry should be 1–3
lines plus links / notes.

## 2026-06-27

### 双 3090 WSL2 部署完成 — 单机双卡对等集群

- **Status**: Completed
- **Description**: 按 `docs/3090-wsl2-deployment-guide.md（双卡版）` 完成完整部署：
  - 仓库克隆、uv venv + pyproject.toml、依赖安装（torch 2.9.1, sglang, pymupdf, ninja）
  - Windows 防火墙放行 + 端口转发 10001/10002
  - 两个 Gateway 实例：GPU0 → 10001, GPU1 → 10002，`--peers` 互指
  - 修复 peer 健康探测递归阻塞问题（缓存化 + 后台 15s 轮询），health 响应从 ~6s 降至 ~0.18s
  - 双卡 peer 互检 online，`best_target` 自动选择空闲卡

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

# Bug Log

Resolved bugs and their root causes, organized by date (newest first).

## 2026-07-01

### Ninja not on PATH（再次发生，代码层根治）

- **Issue**: 重启 gateway server 后，用户再次上传文件，SGLang JIT 编译 rotary kernel
  时报 `FileNotFoundError: [Errno 2] No such file or directory: 'ninja'`。
  尽管 gateway server 的 PATH 已含 `.venv/bin`，SGLang 子进程仍然找不到 `ninja`。
- **Root Cause**: `inference/batch.py:start_server()` 中 `env = os.environ.copy()`
  继承的 PATH 在父进程正确，但 SGLang 内部通过 `multiprocessing.set_executable()`
  创建 shell 脚本包装器调用 `numactl`，导致 JIT 子进程（`tvm_ffi.build_ninja`）
  的搜索路径丢失。单纯在启动命令加 PATH 不够稳固。
- **Solution**: 在 `inference/batch.py` `start_server()` 中显式将 venv bin 目录
  注入 `env["PATH"]`：
  ```python
  venv_bin = os.path.dirname(sys.executable)
  env["PATH"] = f"{venv_bin}:{env.get('PATH', '')}"
  ```
  这样不管父进程 PATH 如何，SGLang 子进程一定能找到 `ninja`。
- **Prevention**:
  1. 代码层：`inference/batch.py` 已加显式 PATH 注入，后续改 `start_server()`
     逻辑时注意不要去掉。
  2. 运维层：`key_facts.md` 启动命令速查保留正确示例。
  3. 旧的启动命令防护（仅加 PATH 前缀启动）已不够——因 SGLang 内部进程
     树复杂，必须从代码层面保证。

## 2026-06-30

### pandoc 2.12 不支持 `--embed-resources` flag

- **Issue**: Phase A `gateway/convert.py` 调用 `pandoc --embed-resources --standalone`
  生成 HTML 时，开发宿主的 pandoc 2.12 (conda) 报 `Unknown option --embed-resources`，
  转换失败。
- **Root Cause**: `--embed-resources` 是 pandoc 2.19 才引入的，用于替代被废弃的
  `--self-contained`（后者在 pandoc 3.x 被移除）。开发宿主 conda 里的 pandoc 太旧。
- **Solution**: `convert.py` 用 `_pandoc_version()` (lru_cache) 检测版本：
  - `>= (2, 19)` → 用 `--embed-resources --standalone`
  - 旧版 → 用 `--self-contained`（功能等价，pandoc 3.x 才会报 deprecation）
  同时 LaTeX 输出也加了 `--standalone`，否则 pandoc 2.12 只输出片段没有
  `\documentclass`。
- **Prevention**: 调用 pandoc 子进程时不要假设 flag 集合稳定；pandoc 2.x 和 3.x
  的 CLI 有实质差异。版本检测 + 条件 flag 是唯一稳妥方案。Dockerfile 用 apt
  装的 pandoc 通常是 3.x，开发宿主 conda 装的可能是 2.x，两者都要支持。

### `gateway/persist.py` 循环导入：`TaskState` 运行时未定义

- **Issue**: Phase B `persist.py` 顶部 `from .state import TaskState` 导致
  `NameError: name 'TaskState' is not defined` 在 `load_all()` 运行时抛出。
- **Root Cause**: `state.py` 顶部 `from .users import UserRegistry`，而
  `persist.py` 又被 `state.py` 的 TYPE_CHECKING 块引用，形成循环。把
  `TaskState` 放在 `TYPE_CHECKING` 下只对类型检查器可见，运行时 import 不发生，
  但 `load_all()` 函数体里构造 `TaskState(...)` 时名字不存在。
- **Solution**: `persist.py` 顶部 `from typing import TYPE_CHECKING`，只在
  类型检查时导入 `TaskState`；`load_all()` 方法体内做 lazy import
  (`from .state import TaskState`)。`save_task` 接收的 `task` 参数用 duck typing，
  不需要类型注解运行时可用。
- **Prevention**: 跨模块 dataclass + 持久化层容易循环导入。TYPE_CHECKING 只解决
  类型检查器的循环，运行时仍然需要导入。方法内 lazy import 是 stdlib 惯用法，
  比 `importlib` 简单。测试时一定要实际调用 `load_all()` 而不只是 import 通过。

### `_task_to_dict` 未输出 `pdf_name` 字段

- **Issue**: Phase B 给 `TaskState` 加了 `pdf_name` 字段，sqlite 持久化也写了，
  但 API 返回的 task 对象里没有 `pdf_name`。CLI `list` 命令的 `pdf_name` 列
  一直是空的。
- **Root Cause**: 给 dataclass 加字段后忘了同步更新 `_task_to_dict`。sqlite
  表 schema 和 `save_task` 都更新了，但序列化函数漏掉。
- **Solution**: `_task_to_dict` 加 `"pdf_name": task.pdf_name`。
- **Prevention**: 给 `TaskState` 加字段时有三处必须同步：dataclass 定义、
  `_task_to_dict` 输出、`persist.py` schema + save_task + load_all。建议加一个
  字段对照表检查清单。API 契约文档也要同步更新。

### subagent 返回空结果（无文件改动）

- **Issue**: Phase A 后端实施时，给 subagent 下发完整任务，subagent 报告
  "completed" 但实际 0 文件改动、`git status` 干净。
- **Root Cause**: 未知。subagent 可能在工具调用过程中失败但未报错，或误判
  任务完成。后续 subagent 调用都正常。
- **Solution**: coordinator 直接实施后端代码，后续 subagent 调用正常工作。
- **Prevention**: subagent 报告 completed 后，coordinator 必须用
  `git status` / `git diff --stat` 验证实际改动，不能只看 subagent 自述。
  空结果要立即重做或自己实施，不要重复派发同一任务。

## 2026-06-26

### SGLang subprocess fails with `FileNotFoundError: 'ninja'` on first request（见 07-01 代码层根治）

- **Issue**: After uploading a PDF via the LAN service, the task failed with
  `SGLang server exited early. Check <workdir>/logs/<id>_sglang.log` and the
  log showed `FileNotFoundError: [Errno 2] No such file or directory: 'ninja'`
  inside the rotary-embedding JIT build step.
- **Root Cause**: `python -m sglang.launch_server` (started by
  `inference.batch.start_server`) shells out to `ninja` to JIT-build the
  rotary kernel on the first request. When `gateway/server.py` was launched
  as `/path/.venv/bin/python -m gateway.server`, the subprocess PATH did
  not include `.venv/bin/`, so `ninja` was not findable. The bundled sglang
  wheel is JIT-heavy and the venv's `ninja` binary is the only place it
  lives.
- **Solution**: Launch with `source .venv/bin/activate` first, or
  `PATH=/path/.venv/bin:$PATH python -m gateway.server`. No code change.
- **Prevention**: 第一次（06-26）仅在文档和 AGENTS.md 记录启动方式，
  但未从代码层面防护。07-01 复发后在 `inference/batch.py:start_server()`
  做了代码层根治（显式注入 venv bin 到 PATH）。具体见 07-01 条目。

### `ResultViewer` ZIP extraction: whole-blob inflate (no `<|det|>` to fix here, wrong method)

- **Issue**: First implementation called `new DecompressionStream('deflate-raw')`
  on the entire ZIP blob as if it were a single deflate stream. ZIPs are a
  container with per-entry deflate, so nothing decoded.
- **Root Cause**: Misread how ZIP is structured; assumed "the whole thing is
  one stream". The marker was that `unzip -l` of the server's output worked
  fine, so the bytes were valid — only the browser-side decoder was wrong.
- **Solution**: Replaced with `fflate`'s `unzipSync(uint8Array)` which handles
  per-entry deflate correctly. ~9 KB minified, no async dependency, works in
  the browser. Lives in `clients/web/src/components/ResultViewer.vue`.
- **Prevention**: When decoding ZIP/TAR/7z in the browser, always use a
  purpose-built library (`fflate`, `jszip`, `client-zip`). Do not roll your
  own with `DecompressionStream`.

### Vite `@/` alias only in `tsconfig.json` — typecheck passes, build fails

- **Issue**: `pnpm typecheck` was green but `pnpm build` errored with
  `Rollup failed to resolve import "@/composables/useSettings" from "App.vue"`.
- **Root Cause**: TypeScript's `paths` config makes `vue-tsc` happy, but
  Vite's bundler (Rollup) needs its own `resolve.alias` in `vite.config.ts`
  to actually rewrite the import at build time. The two are independent.
- **Solution**: Added `resolve.alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) }`
  to `clients/web/vite.config.ts`.
- **Prevention**: Whenever a path alias is added, update **both** `tsconfig.json`
  (for the editor + `vue-tsc`) and `vite.config.ts` (for the bundler) together.
  Documented in the Web Frontend "Vite alias" subsection of `AGENTS.md`.

### `CORSMiddleware` added to FastAPI app silently ignored at runtime

- **Issue**: First CORS attempt used the textbook
  `app.add_middleware(CORSMiddleware, ...)` inside an argparse branch in `main()`.
  The browser still saw `No 'Access-Control-Allow-Origin' header`.
- **Root Cause**: FastAPI builds the middleware stack lazily on the first
  request, and `add_middleware` after construction is silently a no-op in some
  paths. Re-adding the middleware does not replace an existing entry.
- **Solution**: Wrote a `configure_cors(origins)` helper that explicitly clears
  `app.user_middleware` of any previous `CORSMiddleware`, sets
  `app.middleware_stack = None`, then re-adds the middleware. Forces a
  fresh stack build on the next request. (In the latest `gateway/server.py`
  the CORS middleware is installed at module import time instead — see the
  Phase 4 commit on `main` for the simpler approach.)
- **Prevention**: When wiring middleware from a CLI / config branch (not at
  module import time), use the `clear → reset stack → add` dance. Documented
  in `AGENTS.md` Pitfall #15.

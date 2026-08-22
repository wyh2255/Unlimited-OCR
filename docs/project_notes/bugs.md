# Bug Log

Resolved bugs and their root causes, organized by date (newest first).

## 2026-08-22

### start_server.sh 用 setsid 导致 pidfile 记录死 PID，幂等检查失效

- **Issue**: 初版 `start_server.sh` 用 `setsid nohup python ... &` 后台启动，
  pidfile 写入的 `$!` 是 setsid 的 PID——setsid fork 后立即退出，真正的网关
  进程是另一个 PID。重复执行脚本时 `kill -0 $(cat pidfile)` 判定"未运行"，
  于是又拉起一个实例（后者因端口占用退出）。
- **Root Cause**: `setsid` 无参数调用时会 fork 出新会话再 exec，父进程即刻退出，
  shell 的 `$!` 与最终进程 PID 不一致。
- **Solution**: 改为裸 `nohup python ... & disown`——nohup+输出重定向已足够
  脱离终端，且 `$!` 就是真实网关 PID；幂等检查同时加 curl health 探测兜底。
- **Prevention**: 需要记录后台进程 PID 时不要用无参数 `setsid`；
  幂等检查用服务自身的 health 端点而不是只信 pidfile。

### 本机无 ss/netstat/lsof/fuser，脚本端口检查静默失效

- **Issue**: start_server.sh 初版用 `ss -tln | grep :PORT` 检查端口占用，
  本机没有 ss 命令，`2>/dev/null` 把报错吞掉后 grep 匹配空输出 → 检查形同虚设，
  已被占用的端口通过了检查。
- **Root Cause**: 精简容器/服务器未装 iproute2 工具集；错误重定向掩盖了命令不存在。
- **Solution**: 统一改用 `curl -sf -m2 http://127.0.0.1:$PORT/api/v1/health`
  （已在跑则提示退出）+ bash `/dev/tcp` 探测（通但 health 不响应则报错）。
- **Prevention**: 在这台机器上写端口探测逻辑只用 curl 或 /dev/tcp，
  不要引入 ss/netstat/lsof 依赖（AGENTS.md「本机特有事实」有记录）。

## 2026-07-26

### sgl_kernel 缺少 sm89 变体，RTX 4090 (sm89) 需强制 SGL_KERNEL_ARCH=90

- **Issue**: SGLang server 启动失败，sgl_kernel 报 `Could not load any common_ops library!`。
  GPU 是 RTX 4090 (compute capability 8.9, SM89)，但 sgl_kernel 只有 sm90 和 sm100 变体。
- **Root Cause**: 定制 sglang wheel 的 sgl_kernel 只打包了 sm90 (RTX 5090) 和 sm100 (未来架构)
  的预编译二进制。SM89 没有对应二进制，且自动选择逻辑不会 fallback 到兼容架构。
- **Solution**: 设置环境变量 `SGL_KERNEL_ARCH=90` 强制使用 SM90 变体（SM90 二进制可后向兼容
  SM89 的大部分功能）。
- **Prevention**: 启动时始终设置 `SGL_KERNEL_ARCH=90`（从 `inference/batch.py` 或启动脚本）。
  RTX 4090 用户开机启动必须包含此环境变量。

### libnuma.so.1 缺失导致 sgl_kernel 加载失败

- **Issue**: sgl_kernel 的 sm100/common_ops.abi3.so 依赖 libnuma.so.1，但系统缺少。
- **Root Cause**: 容器/系统未安装 `libnuma-dev`/`libnuma1`，导致动态链接失败。
- **Solution**: `apt install -y libnuma-dev`
- **Prevention**: 环境准备步骤中补充 `apt install -y libnuma-dev g++`。

### g++ 缺失导致 SGLang JIT kernel 编译失败

- **Issue**: SGLang JIT (tvm_ffi) 调用 ninja + nvcc 编译 fused_rope kernel 时，
  `gcc: fatal error: cannot execute 'cc1plus': execvp: No such file or directory`。
- **Root Cause**: 系统没有安装 g++。nvcc 的前端编译器需要 g++/cc1plus 来处理 host 端代码。
- **Solution**: `apt install -y g++`
- **Prevention**: 环境准备步骤中补充 g++。

### flash_attn 命名空间包缺少核心函数

- **Issue**: 模型加载时 `from flash_attn import flash_attn_func` 报 `ImportError`。
- **Root Cause**: sglang 定制 wheel 安装了一个 flash_attn 命名空间包（无 `__init__.py`），
  只有一个 `cute/` 子目录，不包含 `flash_attn_func` 等核心函数。但
  `is_flash_attn_2_available()` 检测到包存在（版本号 4.0.0b19），返回 True，
  导致模型代码尝试导入不存在的函数。
- **Solution**: 修改 `Unlimited-OCR/modeling_deepseekv2.py`，在 `is_flash_attn_2_available()`
  为 True 的情况下用 `try/except ImportError` 包裹导入语句，静默跳过。
- **Prevention**: 安装 flash-attn 完整包失败（CUDA 版本 13.2 vs torch 12.8 不匹配），
  所以只能修改模型代码做降级处理。

### transformers 5.3.0 移除了 is_torch_fx_available

- **Issue**: 模型代码 `from transformers.utils.import_utils import is_torch_fx_available` 报错。
- **Root Cause**: sglang 定制 wheel 安装了 transformers 5.3.0，但该版本已移除
  `is_torch_fx_available` 函数（被 `is_torch_fx_proxy` 替代）。模型代码基于旧版 transformers。
- **Solution**: 修改 `Unlimited-OCR/modeling_deepseekv2.py`，用 `try/except ImportError`
  提供兼容 fallback 实现。
- **Prevention**: 如果未来升级 transformers，需要同步检查模型代码的 import 兼容性。

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

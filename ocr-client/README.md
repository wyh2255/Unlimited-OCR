---
日期: 2026-06-26
文档类型: 用户使用手册
文档概述: ocr-client 包的安装、配置、使用说明（Unlimited-OCR 局域网服务的客户端）
---

# ocr-client

> CLI 客户端 for Unlimited-OCR 局域网服务。装在笔记本上,一行命令上传 PDF 到 GPU 服务器并取回结果。

## 0. 架构说明（2026-06-26 更新）

`ocr-client/` 这个目录现在是一个**构建产物占位符**，不是源码。

- **真实源码**：[`clients/python-cli/src/ocr_client/`](https://github.com/anomalyco/opencode/tree/main/Unlimited-OCR/clients/python-cli/src/ocr_client)（一份代码、单一来源、可以 `pip install -e` 开发模式使用）
- **本目录的作用**：把上面的源码打成 wheel 放进 `ocr-client/dist/`，方便那些不 clone 整个仓库、只想 `uv tool install ./ocr-client` 装一个 wheel 的用户
- **打包方式**：`bash scripts/build_ocr_client.sh`（idempotent，重跑会覆盖）

> 如果你是开发者，请直接 `pip install -e clients/python-cli/[rich]`，**不要**碰这个目录。

## 1. 这是什么

`ocr-client` 是 [`Unlimited-OCR` 仓库](https://github.com/anomalyco/opencode/tree/main/Unlimited-OCR) 里 `server.py` 网关的独立客户端包。打包后可以单独分发,不需要 clone 整个仓库,不需要 GPU,只需要 `python` 和 `requests`(可选 `rich` 增强体验)。

它做的事情:
- 上传 PDF 到 `server.py` 的 `:10001` 端口
- 轮询任务状态(自动降级并发由服务器端决定)
- 下载结果 zip 并解压到本地
- 删除任务释放磁盘
- 健康检查

## 2. 安装

### 2.1 用 `uv tool install`(推荐,全局命令)

```bash
# 从本地源码安装(开发模式,代码改了重装即可)
uv tool install /path/to/ocr-client

# 从 git 安装(等以后推到 remote 后)
uv tool install "ocr-client @ git+https://github.com/anomalyco/opencode.git#subdirectory=ocr-client"
```

装完后就有 `ocr-client` 全局命令。

### 2.2 用 `uvx`(一次性运行,不安装)

```bash
uvx --from /path/to/ocr-client ocr-client --help
```

### 2.3 用 `pip`

```bash
pip install /path/to/ocr-client
# 或者从源码目录:
pip install .
```

> **⚠️ Ubuntu 24+ / 较新 Linux 系统注意**:系统的 Python 默认开启 PEP 668 (externally-managed-environment),直接 `pip install` 会被拒。三种解决方式:
>
> ```bash
> # 方式 A:用 venv 隔离(推荐)
> python3 -m venv ~/.ocr-client-venv
> source ~/.ocr-client-venv/bin/activate
> pip install /path/to/ocr-client
> ocr-client --help
>
> # 方式 B:用 pipx (全局可用但不污染 site-packages)
> pipx install /path/to/ocr-client
>
> # 方式 C:用 --break-system-packages (不推荐,会污染系统包)
> pip install --break-system-packages /path/to/ocr-client
> ```
>
> 想省事的话,直接走 §2.1 的 `uv tool install`,`uv` 会自己处理 PEP 668。

### 2.4 启用 rich 进度条(可选)

```bash
uv tool install "ocr-client[rich]" --force
# 或者后装
uv tool run --from "rich" ocr-client ...
```

`rich` 只是美化输出(进度条、表格)。没装也能跑,只是没进度条。

## 3. 配置

两个环境变量:

| 变量 | 必填 | 默认 | 说明 |
|---|---|---|---|
| `OCR_SERVER` | 否 | `http://127.0.0.1:10001` | 服务端地址 |
| `OCR_API_TOKEN` | 否(但实际必填) | `None` | Bearer token,服务端在 `OCR_API_TOKEN` 环境变量未设置时自动生成并打印 |

写进 `~/.bashrc` / `~/.zshrc` / `.env` 二选一:

```bash
export OCR_SERVER="http://172.17.166.37:10001"
export OCR_API_TOKEN="<服务器启动日志里那个 token>"
```

## 4. 使用

### 4.1 上传 + 等 + 下载(一键)

```bash
ocr-client upload my.pdf --watch
# 等几分钟后输出:
#   uploaded task_id=abc123def456  image_mode=base
#   status -> running
#   [##############------------] 4/8  running
#   status -> completed
#   saved ./out/abc123def456.zip
#   extracted ./out/abc123def456/
```

### 4.2 分步操作

```bash
# 提交
TASK_ID=$(ocr-client upload my.pdf | tail -1)
# 只打印 task_id 到 stdout,方便脚本里接

# 轮询
ocr-client status $TASK_ID --watch

# 下载并解压
ocr-client download $TASK_ID --out ./out

# 清理
ocr-client delete $TASK_ID
```

### 4.3 所有子命令

| 子命令 | 用途 |
|---|---|
| `ocr-client upload <pdf> [--watch] [--out DIR] [--image-mode base\|gundam] [--concurrency-hint N]` | 上传 PDF |
| `ocr-client status <task_id> [--watch]` | 查询状态/进度 |
| `ocr-client download <task_id> [--out DIR]` | 下载并解压 zip |
| `ocr-client delete <task_id>` | 删任务 + 服务器端释放磁盘 |
| `ocr-client health` | 健康检查(免鉴权) |

### 4.4 全局参数

```
--server URL   覆盖 $OCR_SERVER
--token TOKEN  覆盖 $OCR_API_TOKEN
```

例子:

```bash
ocr-client --server http://192.168.1.50:10001 --token abc123... health
```

> 注意:`health` 端点本身**不需要** token,但 ocr-client 仍接受 `--token` 参数(版本 ≥ 0.1.1 起),让脚本能统一给所有子命令传参而不报错。

## 5. 跟 server.py 的关系

```
笔记本(装 ocr-client)         服务器(装 Unlimited-OCR + server.py)
┌──────────────────┐         ┌────────────────────────────────┐
│  ocr-client      │  HTTP   │  server.py :10001              │
│  upload / status │◄───────►│      ↓ worker                  │
│  download        │  :10001 │      ↓ run_inference()         │
└──────────────────┘  Bearer │      ↓ SGLang :10000          │
                            │      ↓ postprocess_sglang.py   │
                            │      ↓ zip                     │
                            └────────────────────────────────┘
```

详细 API 契约见 [`API_CONTRACT.md`](../API_CONTRACT.md)。

## 6. 故障排查

**Q1. `401 invalid token`**
检查 `OCR_API_TOKEN` 是否和服务端 `OCR_API_TOKEN` 一致;服务端启动时如果没设环境变量,会自动生成并打印一次,看那个值。

如果看到 `RuntimeError: HTTP 401: invalid token` 后面**没有** Python traceback 栈帧,说明你用的版本 ≥ 0.1.1(干净的错误输出);如果还看到 `Traceback (most recent call last):` 开头,说明版本较旧,请升级。

**Q2. `Cannot reach server` / Connection refused**
- 确认 `OCR_SERVER` 拼写对、端口对(默认 `:10001`)
- 确认服务端在跑:`curl $OCR_SERVER/api/v1/health`
- 确认防火墙: `iptables -L -n` 或 `ufw status`

**Q3. `Task failed; no result zip available`**
任务在 OCR 阶段失败了。看服务端日志:
```bash
tail -100 /path/to/Unlimited-OCR/api_workdir/logs/<task_id>_sglang.log
```
或服务端 stdout(`/path/to/Unlimited-OCR/log/api_server.log`)。

**Q4. rich 没装会怎样?**
不会崩。进度条降级为 ASCII 字符:`[####------] 4/8  running`。

## 7. 开发

```bash
cd /path/to/ocr-client
uv venv
source .venv/bin/activate
uv pip install -e ".[rich]"

# 本地跑
ocr-client --help

# 跑测试
uvx --from build hatchling build  # 构建 wheel
ls dist/
```

## 8. 许可

MIT

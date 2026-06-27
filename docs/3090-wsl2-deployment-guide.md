---
日期: 2026-06-27
文档类型: 部署指南
文档概述: 双 RTX 3090 (Windows 10 WSL2) 部署 Unlimited-OCR 对等调度节点的完整步骤。配合 A100 宿主机组成多 GPU 集群。
---

# 3090 WSL2 部署指南（双卡版）

## 前置条件

| 项目 | 要求 |
|------|------|
| 操作系统 | Windows 10 22H2+ |
| GPU | 2× NVIDIA RTX 3090（每张 24 GB VRAM，合计 48 GB） |
| 驱动 | NVIDIA Game Ready 或 Studio 驱动 ≥ 545 |
| 磁盘 | ≥ 50 GB 可用空间 |
| 内存 | ≥ 32 GB 系统内存 |
| 网络 | 与 A100 服务器同一局域网，互通 10001~10002 端口 |

> 双卡方案：每张 3090 各跑一个独立的 Gateway 实例（端口不同），通过 `--peers` 互相发现。
> SGLang 不需要同时看到两张卡——每张卡独立启动自己的 SGLang server。

---

## 第 1 步：启用 WSL2 ✅ 已完成

以 **管理员身份** 打开 PowerShell 执行：

```powershell
# 启用 WSL2 并安装 Ubuntu 24.04 LTS
wsl --install -d Ubuntu-24.04

# 重启计算机
Restart-Computer
```

重启后继续：

```powershell
# 确认 WSL2 版本
wsl -l -v
# 输出应显示: Ubuntu-24.04  Running  2
```

---

## 第 2 步：WSL2 内基础环境 ✅ 已完成

进入 WSL2：

```powershell
wsl -d Ubuntu-24.04
```

以下命令全部在 WSL2 的 bash 中执行：

```bash
# 更新系统包
sudo apt update && sudo apt upgrade -y

# 安装基础工具
sudo apt install -y curl git wget build-essential

# 安装 Python 3.12 + uv
sudo apt install -y python3.12 python3.12-venv python3-pip
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc  # 或重新打开 shell
```

确认 Python 和 uv：

```bash
python3.12 --version   # Python 3.12.x
uv --version            # uv 0.x.x
```

---

## 第 3 步：安装 CUDA Toolkit (WSL2 专用) ✅ 已完成

WSL2 的 CUDA 安装方式与原生 Linux 不同——GPU 驱动在 Windows 端，WSL2 内只装 toolkit：

```bash
# CUDA 12.6 WSL2 专用源
wget https://developer.download.nvidia.com/compute/cuda/repos/wsl-ubuntu/x86_64/cuda-keyring_1.1-1_all.deb
sudo dpkg -i cuda-keyring_1.1-1_all.deb
sudo apt update

# 安装 CUDA Toolkit 12.6 (不包含驱动)
sudo apt install -y cuda-toolkit-12-6
```

验证 GPU 可见：

```bash
nvidia-smi
# 输出应显示 2 张 RTX 3090
```

---

## 第 4 步：克隆仓库 + 创建 venv + pyproject.toml

```bash
cd ~
git clone <your-repo-url> Unlimited-OCR
cd Unlimited-OCR
```

> 如果没有远程仓库，从 A100 机器上 `rsync`（跳过已有的 `.venv` 和模型）：
> ```bash
> rsync -avz user@<A100_IP>:/path/Unlimited-OCR/ ~/Unlimited-OCR/ \
>   --exclude='.venv' --exclude='Unlimited-OCR/'
> ```

```bash
# 创建虚拟环境（基于 pyproject.toml 中的 Python 版本约束）
uv venv --python 3.12
source .venv/bin/activate

# 确认在 venv 中
which python  # 应指向 ~/Unlimited-OCR/.venv/bin/python
```

项目的 `pyproject.toml` 已存在于仓库根目录，无需手动创建。`uv venv` 会自动读取其中的 `requires-python` 约束。如果后续需要添加项目元数据或依赖声明，编辑 `pyproject.toml` 即可。

---

## 第 5 步：安装依赖

```bash
# SGLang 定制 wheel（永不用 PyPI 版本替换，参见 Pitfall #14 需要 ninja）
uv pip install wheel/sglang-0.0.0.dev11416+g92e8bb79e-py3-none-any.whl

# 核心依赖
uv pip install kernels==0.11.7 pymupdf==1.27.2.2

# LAN 网关依赖
uv pip install -r requirements-api.txt

# ninja（SGLang JIT 用 — Pitfall #14）
uv pip install ninja
```

验证关键依赖：

```bash
python -c "import torch; print('torch', torch.__version__)"
python -c "import sglang; print('sglang', sglang.__version__)"
python -c "from gateway.peers import PeerConfig; print('peers ok')"
python -m gateway.server --help
```

---

## 第 6 步：拷贝模型权重 ✅ 已完成

> 模型权重已下载完成，跳过本步。确认模型可用：
> 
> ```bash
> ls -lh Unlimited-OCR/
> # 应看到: model-00001-of-000*.safetensors, config.json, ...
> du -sh Unlimited-OCR/  # 应约 6.4 GB
> ```

---

## 第 7 步：Windows 防火墙 + 端口转发（双卡需转发两个端口）

WSL2 每次重启 IP 会变，需要从 Windows 侧做端口转发。在 **管理员 PowerShell** 中执行：

```powershell
# === Windows 防火墙放行（10001 + 10002） ===
netsh advfirewall firewall add rule name="Unlimited-OCR 10001" dir=in action=allow protocol=tcp localport=10001
netsh advfirewall firewall add rule name="Unlimited-OCR 10002" dir=in action=allow protocol=tcp localport=10002

# === 自动获取 WSL2 IP + 端口转发（两张卡各一个端口） ===
$wslIp = (wsl -d Ubuntu-24.04 hostname -I).Trim().Split()[0]
netsh interface portproxy add v4tov4 listenport=10001 listenaddress=0.0.0.0 connectaddress=$wslIp connectport=10001
netsh interface portproxy add v4tov4 listenport=10002 listenaddress=0.0.0.0 connectaddress=$wslIp connectport=10002

# 确认转发生效
netsh interface portproxy show all
```

> **每次重启 Windows 或 WSL2 后需要重新执行端口转发**（因为 WSL2 IP 会变）。
> 建议创建一个 `start-ocr-proxy.ps1` 脚本双击运行：
> ```powershell
> $wslIp = (wsl -d Ubuntu-24.04 hostname -I).Trim().Split()[0]
> netsh interface portproxy add v4tov4 listenport=10001 listenaddress=0.0.0.0 connectaddress=$wslIp connectport=10001
> netsh interface portproxy add v4tov4 listenport=10002 listenaddress=0.0.0.0 connectaddress=$wslIp connectport=10002
> Write-Host "OCR 端口转发已设置: localhost:10001/10002 → $wslIp`:10001/10002"
> ```

---

## 第 8 步：启动 Gateway（双卡单机模式）

双 3090 各跑一个独立的 Gateway 实例，通过 `--peers` 互相发现。打开 **两个 WSL2 终端**（或使用 `tmux` / 后台进程）。

> 每张卡运行独立的 SGLang 后端，互不抢占 VRAM。

```bash
# === 终端 1：GPU 0，端口 10001 ===
cd ~/Unlimited-OCR
source .venv/bin/activate

export OCR_API_TOKEN="<与你 A100 相同的 token，或新生成>"
# 双卡并发阈值：每张卡独立检测，24GB 单卡的配置不变
export OCR_CONCURRENCY_TIERS="16:4,6:2,0:1"

python -m gateway.server \
    --host 0.0.0.0 \
    --port 10001 \
    --gpu 0 \
    --model-dir ./Unlimited-OCR \
    --workdir ./api_workdir_gpu0 \
    --peers "http://127.0.0.1:10002,<token>"
```

```bash
# === 终端 2：GPU 1，端口 10002 ===
cd ~/Unlimited-OCR
source .venv/bin/activate

export OCR_API_TOKEN="<同一 token>"
export OCR_CONCURRENCY_TIERS="16:4,6:2,0:1"

python -m gateway.server \
    --host 0.0.0.0 \
    --port 10002 \
    --gpu 1 \
    --model-dir ./Unlimited-OCR \
    --workdir ./api_workdir_gpu1 \
    --peers "http://127.0.0.1:10001,<token>"
```

在 Windows 浏览器分别打开以下地址确认两套实例健康：

- `http://localhost:10001/api/v1/health`
- `http://localhost:10002/api/v1/health`

两个 health 都应返回 `status: ok`，且 `peers` 字段显示对方 `online: true`。

---

## 第 9 步：接入对等调度（双卡 + A100 组网）

确认 A100 的 IP 可达：

```powershell
# 在 Windows PowerShell 测试
ping <A100_IP>
```

在 A100 上添加 `--peers` 指向 3090 的两张卡：

```bash
# === A100 端 ===
source .venv/bin/activate
export OCR_API_TOKEN="<公共 token>"

python -m gateway.server \
    --port 10001 \
    --gpu 0 \
    --model-dir ./Unlimited-OCR \
    --peers "http://<3090_Windows_IP>:10001,<token>" \
    --peers "http://<3090_Windows_IP>:10002,<token>"
```

在 3090 的两个 Gateway 上都添加 `--peers` 指向 A100（以及彼此，如果上一步没加）：

```bash
# === 3090 WSL2：终端 1（GPU 0，端口 10001） ===
source .venv/bin/activate
export OCR_API_TOKEN="<公共 token>"
export OCR_CONCURRENCY_TIERS="16:4,6:2,0:1"

python -m gateway.server \
    --host 0.0.0.0 \
    --port 10001 \
    --gpu 0 \
    --model-dir ./Unlimited-OCR \
    --workdir ./api_workdir_gpu0 \
    --peers "http://127.0.0.1:10002,<token>" \
    --peers "http://<A100_IP>:10001,<token>"
```

```bash
# === 3090 WSL2：终端 2（GPU 1，端口 10002） ===
source .venv/bin/activate
export OCR_API_TOKEN="<公共 token>"
export OCR_CONCURRENCY_TIERS="16:4,6:2,0:1"

python -m gateway.server \
    --host 0.0.0.0 \
    --port 10002 \
    --gpu 1 \
    --model-dir ./Unlimited-OCR \
    --workdir ./api_workdir_gpu1 \
    --peers "http://127.0.0.1:10001,<token>" \
    --peers "http://<A100_IP>:10001,<token>"
```

验证组网（两端的 health 都应显示所有 peer online）：

```bash
curl http://127.0.0.1:10001/api/v1/health | python -m json.tool
curl http://127.0.0.1:10002/api/v1/health | python -m json.tool
# 每个 health 的 "peers" 字段应包含所有其他节点，且都 online: true
```

---

## 第 10 步：持久化启动（后台运行双实例）

WSL2 内使用 `setsid + nohup` 分别持久化两个 Gateway 实例：

```bash
cd ~/Unlimited-OCR
source .venv/bin/activate

# 创建日志目录
mkdir -p log

# === 实例 1：GPU 0，端口 10001 ===
setsid nohup python -m gateway.server \
    --host 0.0.0.0 \
    --port 10001 \
    --gpu 0 \
    --model-dir ./Unlimited-OCR \
    --workdir ./api_workdir_gpu0 \
    --peers "http://127.0.0.1:10002,<token>" \
    --peers "http://<A100_IP>:10001,<token>" \
    > log/gateway_gpu0.log 2>&1 < /dev/null &
disown

# === 实例 2：GPU 1，端口 10002 ===
setsid nohup python -m gateway.server \
    --host 0.0.0.0 \
    --port 10002 \
    --gpu 1 \
    --model-dir ./Unlimited-OCR \
    --workdir ./api_workdir_gpu1 \
    --peers "http://127.0.0.1:10001,<token>" \
    --peers "http://<A100_IP>:10001,<token>" \
    > log/gateway_gpu1.log 2>&1 < /dev/null &
disown

# 日志跟踪
tail -f log/gateway_gpu0.log
tail -f log/gateway_gpu1.log
```

> ⚠️ 因为 Pitfall #14，必须在 `source .venv/bin/activate` 之后启动 nohup，否则 `ninja` 不在 PATH 导致 SGLang JIT 失败。

---

## 常见问题

### Q1: `nvidia-smi` 找不到

```
Command 'nvidia-smi' not found
```

**原因**：Windows 驱动没装或 WSL2 的 CUDA toolkit 没装对。
**解决**：
1. 在 Windows 确认 `nvidia-smi` 有输出
2. 在 WSL2 重装 CUDA toolkit（参见第 3 步）

### Q2: `ModuleNotFoundError: No module named 'torch'`

**原因**：没 `source .venv/bin/activate`。
**解决**：
```bash
cd ~/Unlimited-OCR
source .venv/bin/activate
which python  # 确认指向 .venv/bin/python
```

### Q3: 端口转发不生效

```
curl: (56) Recv failure: Connection was reset
```

**原因**：WSL2 IP 变了或防火墙没放行。
**解决**：
```powershell
# 重新设置端口转发
netsh interface portproxy reset
# 然后重新执行第 7 步
```

### Q4: 上传 PDF 后任务卡在 `queued`

**原因**：SGLang JIT ninja 找不到（见 Pitfall #14）。
**解决**：
```bash
ls .venv/bin/ninja  # 应存在
# 如果不存在:
uv pip install ninja
```

### Q5: `rsync` 很慢

```bash
# 使用压缩传输（CPU 换带宽）
rsync -avzP --compress-level=6 user@A100_IP:/path/Unlimited-OCR/Unlimited-OCR/ ./Unlimited-OCR/
```

### Q6: 双卡模式下两个 SGLang 同时启动会冲突吗？

两张卡各自启动独立的 SGLang server。`inference/batch.py` 中 SGLang 默认端口为 10000，但两个 Gateway 实例的 `run_inference` 不会同时运行（FIFO 队列），所以不会冲突。如果偶尔需要并发跑两个任务（分别在不同 GPU 上），SGLang 的端口会冲突——但在当前架构下不会发生。

### Q7: 前端应该配置哪个地址？

建议写一个入口地址（如 A100），或者让前端用负载均衡。参考附录中的配置方案。

### Q8: 两张卡的并发阈值一样吗？

是的，每张 3090 都是 24GB VRAM，使用相同的阈值：
```
OCR_CONCURRENCY_TIERS="16:4,6:2,0:1"
```
每张卡独立检测自己的剩余显存。如果一张卡被其他任务占用，它会自动降低并发数。

---

## 附录：供前端用户配置

当所有机器都启动后，前端可以配置多个地址：

```
主地址 (Server URL): http://<A100_IP>:10001
备用地址 (Fallback 1): http://<3090_Windows_IP>:10001  (GPU 0)
备用地址 (Fallback 2): http://<3090_Windows_IP>:10002  (GPU 1)
Token: <公共 token>
```

> 如果前端不支持多备用地址，建议在前面加一层反向代理（如 nginx）做负载均衡：
> 
> ```nginx
> upstream ocr_cluster {
>     server <A100_IP>:10001 weight=2;
>     server <3090_Windows_IP>:10001;
>     server <3090_Windows_IP>:10002;
> }
> server { listen 10000; location / { proxy_pass http://ocr_cluster; } }
> ```

前端上传时会自动：
1. 探测各端的 `/health`
2. 选择空闲的那个（都空闲选 A100，其次 3090 GPU 0，再其次 GPU 1）
3. 状态查看/下载自动指向提交时那台机器
4. 节点关机后自动降级到下一个可用节点

> 双卡叠加效果：A100 处理 1 个任务的同时，3090 双卡可以各处理 1 个任务，集群总并发吞吐量提升 2~3 倍。

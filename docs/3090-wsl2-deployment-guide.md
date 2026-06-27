---
日期: 2026-06-27
文档类型: 部署指南
文档概述: RTX 3090 (Windows 10 WSL2) 部署 Unlimited-OCR 对等调度节点的完整步骤。配合 A100 宿主机组成双 GPU 集群。
---

# 3090 WSL2 部署指南

## 前置条件

| 项目 | 要求 |
|------|------|
| 操作系统 | Windows 10 22H2+ |
| GPU | NVIDIA RTX 3090（24 GB VRAM） |
| 驱动 | NVIDIA Game Ready 或 Studio 驱动 ≥ 545 |
| 磁盘 | ≥ 50 GB 可用空间 |
| 内存 | ≥ 32 GB 系统内存 |
| 网络 | 与 A100 服务器同一局域网，互通 10001 端口 |

---

## 第 1 步：启用 WSL2

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

## 第 2 步：WSL2 内基础环境

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

## 第 3 步：安装 CUDA Toolkit (WSL2 专用)

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
# 输出应显示 RTX 3090 和驱动版本
```

---

## 第 4 步：克隆仓库 + 创建 venv

```bash
cd ~
git clone <your-repo-url> Unlimited-OCR
cd Unlimited-OCR
```

> 如果没有远程仓库，从 A100 机器上 `rsync`：
> ```bash
> rsync -avz user@<A100_IP>:/path/Unlimited-OCR/ ~/Unlimited-OCR/ --exclude='.venv'
> ```

```bash
# 创建虚拟环境
uv venv --python 3.12
source .venv/bin/activate

# 确认在 venv 中
which python  # 应指向 ~/Unlimited-OCR/.venv/bin/python
```

---

## 第 5 步：安装依赖

```bash
# SGLang 定制 wheel（永不用 PyPI 版本替换）
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

## 第 6 步：拷贝模型权重

模型权重 6.4 GB，不能从 HuggingFace 在 3090 上重新下载（会拉取不同的文件），必须从 A100 拷贝：

```bash
# 方式 A：rsync（推荐，断点续传）
# 在 3090 WSL2 内执行：
rsync -avzP user@<A100_IP>:/path/Unlimited-OCR/Unlimited-OCR/ ./Unlimited-OCR/

# 方式 B：USB 硬盘搬运
# 1. A100 上: tar czf model.tar.gz Unlimited-OCR/
# 2. 拷贝到 Windows 后放在 WSL2 可访问路径
# 3. WSL2 内: tar xzf /mnt/c/Users/<you>/model.tar.gz
```

验证模型可用：

```bash
ls -lh Unlimited-OCR/
# 应看到: model-00001-of-000*.safetensors, config.json, ...
du -sh Unlimited-OCR/  # 应约 6.4 GB
```

---

## 第 7 步：Windows 防火墙 + 端口转发

WSL2 每次重启 IP 会变，需要从 Windows 侧做端口转发。在 **管理员 PowerShell** 中执行：

```powershell
# === Windows 防火墙放行 ===
netsh advfirewall firewall add rule name="Unlimited-OCR 10001" dir=in action=allow protocol=tcp localport=10001

# === 自动获取 WSL2 IP + 端口转发 ===
$wslIp = (wsl -d Ubuntu-24.04 hostname -I).Trim().Split()[0]
netsh interface portproxy add v4tov4 listenport=10001 listenaddress=0.0.0.0 connectaddress=$wslIp connectport=10001

# 确认转发生效
netsh interface portproxy show all
```

> **每次重启 Windows 或 WSL2 后需要重新执行端口转发**（因为 WSL2 IP 会变）。
> 建议创建一个 `start-ocr-proxy.ps1` 脚本双击运行：
> ```powershell
> $wslIp = (wsl -d Ubuntu-24.04 hostname -I).Trim().Split()[0]
> netsh interface portproxy add v4tov4 listenport=10001 listenaddress=0.0.0.0 connectaddress=$wslIp connectport=10001
> Write-Host "OCR 端口转发已设置: localhost:10001 → $wslIp`:10001"
> ```

---

## 第 8 步：启动 Gateway（单机模式）

先启动单机模式确认一切正常：

```bash
cd ~/Unlimited-OCR
source .venv/bin/activate

export OCR_API_TOKEN="<与你 A100 相同的 token，或新生成>"
# 3090 专用并发阈值（24GB VRAM）
export OCR_CONCURRENCY_TIERS="16:4,6:2,0:1"

python -m gateway.server \
    --host 0.0.0.0 \
    --port 10001 \
    --gpu 0 \
    --model-dir ./Unlimited-OCR \
    --workdir ./api_workdir
```

在 Windows 浏览器打开 `http://localhost:10001/api/v1/health` 确认返回健康信息。

---

## 第 9 步：接入对等调度（与 A100 组网）

确认 A100 的 IP 可达：

```powershell
# 在 Windows PowerShell 测试
ping <A100_IP>
```

在 A100 上添加 `--peers` 指向 3090：

```bash
# === A100 端 ===
source .venv/bin/activate
export OCR_API_TOKEN="<公共 token>"

python -m gateway.server \
    --port 10001 \
    --gpu 0 \
    --model-dir ./Unlimited-OCR \
    --peers "http://<3090_Windows_IP>:10001,<token>"
```

在 3090 上添加 `--peers` 指向 A100：

```bash
# === 3090 WSL2 端 ===
source .venv/bin/activate
export OCR_API_TOKEN="<公共 token>"
export OCR_CONCURRENCY_TIERS="16:4,6:2,0:1"

python -m gateway.server \
    --host 0.0.0.0 \
    --port 10001 \
    --gpu 0 \
    --model-dir ./Unlimited-OCR \
    --workdir ./api_workdir \
    --peers "http://<A100_IP>:10001,<token>"
```

验证组网：

```bash
curl http://127.0.0.1:10001/api/v1/health | python -m json.tool
# 应看到 "peers" 字段包含对方，且两家都 online: true
```

---

## 第 10 步：持久化启动（后台运行）

WSL2 内使用 `setsid + nohup` 持久化：

```bash
mkdir -p log
setsid nohup python -m gateway.server \
    --host 0.0.0.0 \
    --port 10001 \
    --gpu 0 \
    --model-dir ./Unlimited-OCR \
    --workdir ./api_workdir \
    --peers "http://<A100_IP>:10001,<token>" \
    > log/gateway.log 2>&1 < /dev/null &
disown

# 日志跟踪
tail -f log/gateway.log
```

> ⚠️ 因为 Pitfall #14，必须 `source .venv/bin/activate` 之后起 nohup，否则 `ninja` 不在 PATH 导致 SGLang JIT 失败。

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

---

## 附录：供前端用户配置

当两台机器都启动后，前端配置：

```
主地址 (Server URL): http://<A100_IP>:10001
备用地址 (Fallback): http://<3090_Windows_IP>:10001
Token: <公共 token>
```

前端上传时会自动：
1. 探测两台的 `/health`
2. 选择空闲的那个（都空闲选 A100）
3. 状态查看/下载自动指向提交时那台机器
4. 一台关机后自动降级

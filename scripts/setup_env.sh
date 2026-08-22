#!/usr/bin/env bash
# =============================================================================
# Unlimited-OCR 服务器 — 一键环境安装脚本（首次部署跑一次即可）
#
# 用法:
#   bash scripts/setup_env.sh [--skip-system] [--model-dir ./Unlimited-OCR]
#
# 做的事情:
#   1. 安装系统依赖 (libnuma-dev / g++ / ninja-build，可选 pandoc)
#   2. 创建 .venv (Python 3.12, uv 管理)
#   3. 安装 sglang 定制 wheel + requirements-api.txt
#   4. 检查模型权重；缺失时从 HuggingFace 下载到 --model-dir
#   5. 验证关键 import
#
# 幂等：重复执行安全。系统包安装失败不阻塞（可能无 sudo），会给出提示。
# =============================================================================
set -euo pipefail
cd "$(dirname "$0")/.."
REPO_DIR="$(pwd)"

SKIP_SYSTEM=0
MODEL_DIR="./Unlimited-OCR"
while [ $# -gt 0 ]; do
    case "$1" in
        --skip-system) SKIP_SYSTEM=1; shift ;;
        --model-dir)   MODEL_DIR="$2"; shift 2 ;;
        *) echo "未知参数: $1"; exit 1 ;;
    esac
done

log()  { printf '\033[1;34m[setup]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn ]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[fail ]\033[0m %s\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# 0. 前置检查
# ---------------------------------------------------------------------------
command -v nvidia-smi >/dev/null 2>&1 \
    || die "未检测到 nvidia-smi。请先安装 NVIDIA 驱动 (>= 550 推荐)。"

log "GPU: $(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader | head -1)"

# ---------------------------------------------------------------------------
# 1. 系统依赖（缺一不可: libnuma/g++ 会导致 sgl_kernel 或 JIT 编译失败）
# ---------------------------------------------------------------------------
if [ "$SKIP_SYSTEM" -eq 0 ]; then
    if command -v apt-get >/dev/null 2>&1; then
        log "安装系统依赖 (libnuma-dev g++ ninja-build)..."
        SUDO=""
        [ "$(id -u)" -ne 0 ] && command -v sudo >/dev/null 2>&1 && SUDO="sudo"
        $SUDO apt-get update -qq || warn "apt-get update 失败，继续尝试安装"
        $SUDO apt-get install -y -qq libnuma-dev g++ ninja-build \
            || warn "系统包安装失败。请手动执行: apt-get install -y libnuma-dev g++ ninja-build"
    else
        warn "未检测到 apt-get，跳过系统包安装。请确保已装 libnuma、g++、ninja-build。"
    fi
else
    log "跳过系统依赖安装 (--skip-system)"
fi

# ---------------------------------------------------------------------------
# 2. Python 虚拟环境 (.venv, Python 3.12)
# ---------------------------------------------------------------------------
if ! command -v uv >/dev/null 2>&1; then
    log "安装 uv ..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

if [ ! -x .venv/bin/python ]; then
    log "创建 .venv (Python 3.12)..."
    uv venv --python 3.12
else
    log ".venv 已存在，跳过创建"
fi
source .venv/bin/activate

# ---------------------------------------------------------------------------
# 3. Python 依赖（sglang 定制 wheel 必须先装，它锁定 torch 等核心版本）
# ---------------------------------------------------------------------------
WHEEL_FILE=$(ls wheel/sglang-*.whl 2>/dev/null | head -1)
[ -n "$WHEEL_FILE" ] || die "找不到 wheel/sglang-*.whl —— 定制 wheel 必须随仓库分发，禁止用 PyPI 版 sglang。"

log "安装 sglang 定制 wheel ($WHEEL_FILE)..."
uv pip install "$WHEEL_FILE"

log "安装 kernels + pymupdf..."
uv pip install kernels==0.11.7 pymupdf==1.27.2.2

log "安装 requirements-api.txt (fastapi/uvicorn/weasyprint 等)..."
uv pip install -r requirements-api.txt || \
    warn "requirements-api.txt 安装有失败项；若仅做 OCR 推理可忽略 weasyprint/pandoc 相关报错"

# ---------------------------------------------------------------------------
# 4. 模型权重（gitignore 了，不在 git 里，需单独下载 ~6.4 GB）
# ---------------------------------------------------------------------------
if [ -f "$MODEL_DIR/config.json" ]; then
    log "模型权重已存在: $MODEL_DIR"
else
    log "模型权重缺失，尝试从 HuggingFace 下载 baidu/Unlimited-OCR (~6.4 GB)..."
    if uv pip install -q "huggingface_hub[cli]" 2>/dev/null; then
        hf download baidu/Unlimited-OCR --local-dir "$MODEL_DIR" \
            || HF_EXIT=$?
        if [ "${HF_EXIT:-0}" -ne 0 ] || [ ! -f "$MODEL_DIR/config.json" ]; then
            warn "自动下载失败（可能无外网）。手动下载方式二选一:"
            warn "  a) hf download baidu/Unlimited-OCR --local-dir $MODEL_DIR"
            warn "  b) git lfs clone https://huggingface.co/baidu/Unlimited-OCR $MODEL_DIR"
            warn "或者启动服务时改用在线模型: MODEL_DIR=baidu/Unlimited-OCR ./start_server.sh"
        fi
    else
        warn "无法安装 huggingface_hub，请手动下载模型到 $MODEL_DIR"
    fi
fi

# ---------------------------------------------------------------------------
# 5. 验证
# ---------------------------------------------------------------------------
log "验证关键 import..."
python - <<'EOF'
import os
os.environ.setdefault("SGL_KERNEL_ARCH", "90")
import torch, sglang, fitz, fastapi  # noqa
print(f"torch {torch.__version__} | cuda available: {torch.cuda.is_available()}")
print(f"sglang OK | pymupdf OK | fastapi OK")
EOF

ls .venv/bin/ninja >/dev/null 2>&1 || warn ".venv/bin/ninja 不存在 (SGLang JIT 需要): .venv/bin/python -m pip install ninja"

log "完成 ✅  下一步:  ./start_server.sh   (一键后台启动网关)"

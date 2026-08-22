#!/usr/bin/env bash
# =============================================================================
# Unlimited-OCR 网关 — 前台启动（调试用，Ctrl+C 直接停止）
#
# 与 start_server.sh 的区别: 不后台化、日志直接打到终端，方便看 SGLang 启动过程。
# 日常使用请用 ./start_server.sh（后台守护）+ ./stop_server.sh。
#
# 用法:
#   ./start_gateway.sh
#   PORT=10002 MODEL_DIR=baidu/Unlimited-OCR ./start_gateway.sh
# =============================================================================
set -euo pipefail
cd "$(dirname "$0")"

[ -x .venv/bin/python ] || { echo "错误: .venv 不存在。请先执行: bash scripts/setup_env.sh" >&2; exit 1; }
source .venv/bin/activate

export HOST="${HOST:-0.0.0.0}"
export PORT="${PORT:-10001}"
export GPU="${GPU:-0}"
MODEL_DIR="${MODEL_DIR:-./Unlimited-OCR}"
export CUDA_HOME="${CUDA_HOME:-/usr/local/cuda}"
export SGL_KERNEL_ARCH="${SGL_KERNEL_ARCH:-90}"

if [ -z "${OCR_API_TOKEN:-}" ]; then
    if [ -s "$HOME/.ocr_token" ]; then
        OCR_API_TOKEN="$(cat "$HOME/.ocr_token")"
    else
        OCR_API_TOKEN="$(python -c 'import secrets;print(secrets.token_urlsafe(24))')"
        printf '%s' "$OCR_API_TOKEN" > "$HOME/.ocr_token"
        chmod 600 "$HOME/.ocr_token"
    fi
fi
export OCR_API_TOKEN

mkdir -p log api_workdir

echo "== Unlimited-OCR gateway =="
echo "   http://${HOST}:${PORT}  GPU=${GPU}  model=${MODEL_DIR}"
echo "   Token: ${OCR_API_TOKEN}"
echo "   (前台模式, Ctrl+C 停止)"
exec python -m gateway.server \
    --host "$HOST" --port "$PORT" \
    --workdir ./api_workdir \
    --model-dir "$MODEL_DIR" \
    --gpu "$GPU" \
    --cors-origin '*'

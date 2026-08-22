#!/usr/bin/env bash
# =============================================================================
# Unlimited-OCR 网关 — 一键后台启动（生产用法）
#
# 用法:
#   ./start_server.sh                    # 默认 0.0.0.0:10001, GPU 0
#   PORT=10002 GPU=1 ./start_server.sh   # 覆盖端口 / GPU
#
# 行为:
#   - 幂等：已有网关在跑则直接退出（先 ./stop_server.sh 再重启）
#   - Token: 优先 $OCR_API_TOKEN > ~/.ocr_token > 自动生成并持久化到 ~/.ocr_token
#   - 日志: log/api_server.log，PID: log/api_server.pid
#   - 停止: ./stop_server.sh
#
# 首次部署请先跑: bash scripts/setup_env.sh
# =============================================================================
set -euo pipefail
cd "$(dirname "$0")"

[ -x .venv/bin/python ] || { echo "错误: .venv 不存在。请先执行: bash scripts/setup_env.sh" >&2; exit 1; }
source .venv/bin/activate

# --- 环境变量（可用环境覆盖；默认值适配本机 RTX 4090）---
export HOST="${HOST:-0.0.0.0}"
export PORT="${PORT:-10001}"
export GPU="${GPU:-0}"
MODEL_DIR="${MODEL_DIR:-./Unlimited-OCR}"
export CUDA_HOME="${CUDA_HOME:-/usr/local/cuda}"
# RTX 4090 (sm89): sgl_kernel 只有 sm90/sm100 变体，必须强制 sm90。
# A100 (sm80) 部署时可 export SGL_KERNEL_ARCH=80 或留空自动检测。
export SGL_KERNEL_ARCH="${SGL_KERNEL_ARCH:-90}"

# --- Token 持久化 ---
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

# --- 幂等检查 ---
# 本机可能没有 ss/netstat/lsof，统一用 curl 探测端口。
PID_FILE="log/api_server.pid"
if curl -sf -m 2 "http://127.0.0.1:${PORT}/api/v1/health" >/dev/null 2>&1; then
    OLD_PID="(pid 文件: $(cat "$PID_FILE" 2>/dev/null || echo 无))"
    echo "网关已在 ${PORT} 端口运行 ${OLD_PID}。如需重启请先: ./stop_server.sh"
    exit 0
fi
if timeout 1 bash -c "</dev/tcp/127.0.0.1/${PORT}" 2>/dev/null; then
    echo "错误: 端口 $PORT 被其他非网关服务占用（health 无响应但端口通）。" >&2
    echo "排查: ps -ef | grep $PORT 或用 fuser/lsof 找到占用进程。" >&2
    exit 1
fi

# --- 后台启动（nohup+disown，关终端不死；$! 即真实网关 PID）---
nohup python -m gateway.server \
    --host "$HOST" --port "$PORT" \
    --workdir ./api_workdir \
    --model-dir "$MODEL_DIR" \
    --gpu "$GPU" \
    --cors-origin '*' \
    > log/api_server.log 2>&1 < /dev/null &
GATEWAY_PID=$!
disown || true
echo "$GATEWAY_PID" > "$PID_FILE"

# --- 启动确认（等 health 就绪；SGLang 首次任务才拉起，网关本身几秒内就绪）---
for _ in $(seq 1 15); do
    curl -sf -m 2 "http://127.0.0.1:${PORT}/api/v1/health" >/dev/null 2>&1 && break
    kill -0 "$GATEWAY_PID" 2>/dev/null || {
        echo "错误: 网关启动失败，日志最后几行:" >&2
        tail -5 log/api_server.log >&2
        exit 1
    }
    sleep 1
done

echo "网关已就绪: http://$(hostname -I 2>/dev/null | awk '{print $1}'):${PORT}  (PID ${GATEWAY_PID})"
echo "Token: ${OCR_API_TOKEN}"
echo "日志: tail -f log/api_server.log"
echo "验证: curl -s http://127.0.0.1:${PORT}/api/v1/health"

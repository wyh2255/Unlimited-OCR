#!/usr/bin/env bash
# =============================================================================
# Unlimited-OCR 网关 — 停止脚本（配套 start_server.sh）
#
# 行为:
#   1. 读 log/api_server.pid，对网关进程发 SIGTERM（优雅退出）
#   2. 若任务正在跑，SGLang 子进程由网关负责回收；等待最多 15s 后确认退出
#   3. 残留兜底：仅当本仓库 workdir 下确有 sglang.launch_server 残留时才提示手动清理
#
# 用法: ./stop_server.sh
# =============================================================================
set -uo pipefail
cd "$(dirname "$0")"

PID_FILE="log/api_server.pid"

stop_pid() {
    local pid="$1"
    kill -TERM "$pid" 2>/dev/null || return 0
    for _ in $(seq 1 15); do
        kill -0 "$pid" 2>/dev/null || { echo "网关 (PID $pid) 已停止"; return 0; }
        sleep 1
    done
    echo "网关 15s 内未退出，发送 SIGKILL..."
    kill -KILL "$pid" 2>/dev/null || true
}

if [ -f "$PID_FILE" ]; then
    PID="$(cat "$PID_FILE")"
    if kill -0 "$PID" 2>/dev/null; then
        stop_pid "$PID"
    else
        echo "PID $PID 已不存在（可能已停止）"
    fi
    rm -f "$PID_FILE"
else
    echo "未找到 $PID_FILE。若你记得端口，可用: fuser -k <port>/tcp 或 kill <pid>"
fi

# 兜底检查：残留的 SGLang 子进程（只提示，不自动杀 —— 避免误伤别人的进程）
sleep 1
if pgrep -f "sglang.launch_server" >/dev/null 2>&1; then
    echo ""
    echo "警告: 检测到残留 SGLang 进程（占用 GPU 显存），请确认后手动清理:"
    ps -ef | grep "sglang.launch_server" | grep -v grep | awk '{print "  PID", $2, $NF}'
    echo "清理命令: pkill -TERM -f sglang.launch_server"
fi

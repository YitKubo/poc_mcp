#!/usr/bin/env bash
# ops-mcp サーバの起動制御。通常は Makefile 経由（make start / stop / status ...）で使う。
#   serverctl.sh run     フォアグラウンド起動
#   serverctl.sh start   バックグラウンド起動（PID: run/server.pid, ログ: run/server.log）
#   serverctl.sh stop    停止
#   serverctl.sh status  状態表示（起動中=0 / 停止中=3）
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

UV="${UV:-uv}"
RUN_DIR=run
PID_FILE="$RUN_DIR/server.pid"
LOG_FILE="$RUN_DIR/server.log"

# 優先順: 呼び出し時の環境変数 > config/server.env > 既定値
#   例: MCP_PORT=9000 make start   （設定ファイルを触らず一時的に上書き）
load_env() {
  local v; declare -A keep=()
  for v in MCP_HOST MCP_PORT MCP_ALLOWED_HOSTS MCP_LOG_LEVEL MCP_CACHE_TTL_SCALE; do
    if [ -n "${!v+x}" ]; then keep[$v]="${!v}"; fi
  done
  if [ -f config/server.env ]; then set -a; . ./config/server.env; set +a; fi
  for v in "${!keep[@]}"; do export "$v=${keep[$v]}"; done
  export MCP_HOST="${MCP_HOST:-127.0.0.1}" MCP_PORT="${MCP_PORT:-8848}"
}

# 0.0.0.0 待受でも疎通確認は 127.0.0.1 で行う
probe_host() { if [ "$MCP_HOST" = "0.0.0.0" ]; then echo 127.0.0.1; else echo "$MCP_HOST"; fi; }
port_open() { (exec 3<>"/dev/tcp/$(probe_host)/$MCP_PORT") 2>/dev/null; }

# PID ファイルが古く、別プロセスが同じ PID を使っている場合に誤って kill しないよう、
# cmdline に server.py が含まれるかまで確認する。
is_running() {
  [ -f "$PID_FILE" ] || return 1
  local pid; pid="$(cat "$PID_FILE")"
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null && tr '\0' ' ' <"/proc/$pid/cmdline" 2>/dev/null | grep -q 'server\.py'
}

cmd_run() { load_env; exec "$UV" run python server.py; }

cmd_start() {
  load_env
  if is_running; then echo "already running (pid $(cat "$PID_FILE"))"; return 0; fi
  if port_open; then echo "ERROR: port $MCP_PORT is already in use by another process" >&2; return 1; fi
  mkdir -p "$RUN_DIR"
  setsid nohup "$UV" run python server.py >"$LOG_FILE" 2>&1 &
  echo $! >"$PID_FILE"
  for _ in $(seq 1 60); do
    if port_open; then
      echo "started (pid $(cat "$PID_FILE"))  http://$(probe_host):$MCP_PORT/mcp  log: $LOG_FILE"
      return 0
    fi
    if ! is_running; then
      echo "ERROR: server exited during startup. last log lines:" >&2
      tail -n 20 "$LOG_FILE" >&2
      rm -f "$PID_FILE"
      return 1
    fi
    sleep 0.25
  done
  echo "ERROR: timed out waiting for port $MCP_PORT (see $LOG_FILE)" >&2
  return 1
}

cmd_stop() {
  if ! is_running; then echo "not running"; rm -f "$PID_FILE"; return 0; fi
  local pid; pid="$(cat "$PID_FILE")"
  kill "$pid"
  for _ in $(seq 1 40); do
    if ! is_running; then rm -f "$PID_FILE"; echo "stopped (pid $pid)"; return 0; fi
    sleep 0.25
  done
  # uv run は exec せず python を子として起動する。setsid 済みなので pgid==pid。
  # グループ単位で kill しないと SIGKILL 時に子（実サーバ）が孤児として残る。
  echo "did not stop within 10s; sending SIGKILL to process group" >&2
  kill -9 -- "-$pid" 2>/dev/null || kill -9 "$pid" 2>/dev/null || true
  rm -f "$PID_FILE"
}

cmd_status() {
  load_env
  if is_running; then
    echo "running (pid $(cat "$PID_FILE"))  http://$(probe_host):$MCP_PORT/mcp  port_open=$(port_open && echo yes || echo no)"
  else
    echo "stopped"
    return 3
  fi
}

case "${1:-}" in
  run) cmd_run ;; start) cmd_start ;; stop) cmd_stop ;; status) cmd_status ;;
  *) echo "usage: $0 {run|start|stop|status}" >&2; exit 2 ;;
esac

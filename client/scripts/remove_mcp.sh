#!/usr/bin/env bash
# MCP サーバの登録を解除する（claude mcp remove）。scope は自動判別。
. "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
command -v claude >/dev/null || { echo "ERROR: claude コマンドが見つかりません" >&2; exit 1; }
if ! claude mcp get "$MCP_SERVER_NAME" >/dev/null 2>&1; then echo "登録されていません: $MCP_SERVER_NAME"; exit 0; fi
claude mcp remove "$MCP_SERVER_NAME"

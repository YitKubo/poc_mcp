#!/usr/bin/env bash
# MCP サーバを Claude Code に登録する（claude mcp add）。
. "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
command -v claude >/dev/null || { echo "ERROR: claude コマンドが見つかりません" >&2; exit 1; }

if claude mcp get "$MCP_SERVER_NAME" >/dev/null 2>&1; then
  echo "既に登録済みです: $MCP_SERVER_NAME"
  echo "  作り直すには: make reset    削除するには: make remove"
  claude mcp get "$MCP_SERVER_NAME"; exit 0
fi

# 注: local scope は「登録時のカレントディレクトリ」に紐づく。make はこの client/ で実行される。
echo "+ claude mcp add --transport http --scope $MCP_SCOPE $MCP_SERVER_NAME $MCP_SERVER_URL"
claude mcp add --transport http --scope "$MCP_SCOPE" "$MCP_SERVER_NAME" "$MCP_SERVER_URL" || exit $?
echo
claude mcp get "$MCP_SERVER_NAME"
cat <<MSG

登録しました。使うには *新しい* claude セッションを起動します（起動済みのセッションには反映されません）:
  cd $(pwd) && claude          # local scope の場合は、この登録時のディレクトリで起動すること
起動後に /mcp で '$MCP_SERVER_NAME' が connected と表示されれば成功です。
MSG

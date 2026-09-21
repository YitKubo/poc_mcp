# 各スクリプトから source する共通処理。
# 優先順: 呼び出し時の環境変数 > config/endpoint.env > config/endpoint.example.env
#   例: MCP_SERVER_URL=http://192.168.1.10:8848/mcp make check   （設定ファイルを触らず一時的に上書き）
CLIENT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
_pre_name="${MCP_SERVER_NAME:-}"; _pre_url="${MCP_SERVER_URL:-}"; _pre_scope="${MCP_SCOPE:-}"
if [ -f "$CLIENT_DIR/config/endpoint.env" ]; then
  # shellcheck disable=SC1091
  . "$CLIENT_DIR/config/endpoint.env"
else
  # shellcheck disable=SC1091
  . "$CLIENT_DIR/config/endpoint.example.env"
  echo "(note: config/endpoint.env が無いので endpoint.example.env の値を使います。make config で作成できます)" >&2
fi
[ -n "$_pre_name" ] && MCP_SERVER_NAME="$_pre_name"
[ -n "$_pre_url" ] && MCP_SERVER_URL="$_pre_url"
[ -n "$_pre_scope" ] && MCP_SCOPE="$_pre_scope"
: "${MCP_SERVER_NAME:?}" "${MCP_SERVER_URL:?}"
MCP_SCOPE="${MCP_SCOPE:-local}"

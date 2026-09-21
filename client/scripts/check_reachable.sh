#!/usr/bin/env bash
# Claude を介さずに、サーバへ届くかを 3 段階で切り分ける。curl だけで動く（Python 不要）。
#   1. TCP    : ポートに繋がるか        -> 失敗ならサーバ未起動 / 待受アドレス / FW / URL の誤り
#   2. HTTP   : パスに応答があるか      -> 404 なら URL の末尾 /mcp が違う
#   3. MCP    : 本物の tools/list が通るか -> 421 なら サーバ側の Host allowlist（MCP_ALLOWED_HOSTS）
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

URL="$MCP_SERVER_URL"
if [[ ! "$URL" =~ ^https?://([^/:]+)(:([0-9]+))?(/.*)?$ ]]; then echo "ERROR: MCP_SERVER_URL を解釈できません: $URL" >&2; exit 2; fi
HOST="${BASH_REMATCH[1]}"; PORT="${BASH_REMATCH[3]:-80}"
[[ "$URL" == https://* && -z "${BASH_REMATCH[3]}" ]] && PORT=443
echo "target: $URL  (host=$HOST port=$PORT)"

echo -n "1. TCP  connect ...... "
if (exec 3<>"/dev/tcp/$HOST/$PORT") 2>/dev/null; then echo "OK"; else
  echo "FAIL"; echo "   -> $HOST:$PORT に繋がりません。サーバは起動していますか?(server で make status) 待受アドレス/FW/URL も確認。"; exit 1; fi

# 2 と 3 で使う本文。2026-07-28 プロトコルは params._meta と Mcp-Method ヘッダを要求する。
BODY='{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28","io.modelcontextprotocol/clientCapabilities":{}}}}'
OUT="$(mktemp)"; trap 'rm -f "$OUT"' EXIT
CODE="$(curl -sS -m 8 -o "$OUT" -w '%{http_code}' -X POST \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -H 'MCP-Protocol-Version: 2026-07-28' -H 'Mcp-Method: tools/list' -d "$BODY" "$URL" 2>&1)" || CODE=000

echo -n "2. HTTP response ..... "
case "$CODE" in
  000) echo "FAIL (応答なし)"; exit 1 ;;
  404) echo "FAIL (404)"; echo "   -> パスが違います。MCP_SERVER_URL の末尾が /mcp になっていますか?"; exit 1 ;;
  421) echo "FAIL (421 Misdirected Request)"
       echo "   -> サーバの Host ヘッダ allowlist に、この接続先が入っていません。サーバ側の MCP_ALLOWED_HOSTS に '${HOST}' を追加。"
       echo "      (理由はサーバ側のログにしか出ません: server の run/server.log)"; exit 1 ;;
  *)   echo "OK (HTTP $CODE)" ;;
esac

echo -n "3. MCP tools/list .... "
if [ "$CODE" = 200 ]; then
  TOOLS="$(grep -o '"name":"[a-z_]*"' "$OUT" | sed 's/"name":"//; s/"$//' | sort -u | paste -sd, -)"
  echo "OK"; echo "   tools: $TOOLS"
else
  echo "FAIL (HTTP $CODE)"; head -c 300 "$OUT"; echo; exit 1
fi
echo "=> サーバに届いており、MCP として応答しています。次は make add で Claude に登録できます。"

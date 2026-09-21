# 03. トラブルシューティング

まず **`make check`**（Claude 抜きの3段階チェック）で切り分ける。どこで止まるかで原因の層が決まる。

## `make check` の失敗

| 表示 | 原因 | 対処 |
|---|---|---|
| `1. TCP connect ...... FAIL` | ポートに繋がらない: サーバ未起動 / ポート違い / 待受アドレス / FW | サーバ側で `make status`。URL のポート・ホストを確認。別マシンなら `MCP_HOST=0.0.0.0` になっているか |
| `2. HTTP response ..... FAIL (404)` | パスが違う | `MCP_SERVER_URL` の末尾が **`/mcp`** か |
| `2. HTTP response ..... FAIL (421 Misdirected Request)` | サーバの **Host allowlist** に接続先が入っていない | サーバの `MCP_ALLOWED_HOSTS` に URL のホスト部を追加して `make restart`。**理由はサーバの `run/server.log` にしか出ない**（`WARNING Invalid Host header`）。→ [`02-remote-host.md`](02-remote-host.md) |
| `3. MCP tools/list .... FAIL (HTTP 4xx)` | MCP として不正な要求 / プロトコル版の不一致 | 本文（先頭300文字）が表示される。`MCP-Protocol-Version` を上げたサーバに古い形で送っている可能性 |

## Claude Code 側

| 症状 | 原因 | 対処 |
|---|---|---|
| 登録したのに `/mcp` に `ops-mcp` が出ない | **起動済みのセッションには反映されない** | 新しい `claude` セッションを起動する |
| 新しいセッションでも出ない | **local scope は登録時のディレクトリ限定**（`[project: …/client]`） | 登録したディレクトリ（`client/`）で `claude` を起動する。どこからでも使うなら `MCP_SCOPE=user make add` |
| `make add` が `既に登録済みです` | 冪等動作（正常） | 設定を変えて作り直すなら `make reset` |
| `claude mcp list` で ops-mcp が接続できない | サーバ停止・URL 違い | `make check` で層を特定 |
| ツールを呼ぶたびに許可を求められる | 既定の許可確認 | 全ツール read-only なので、`--allowedTools "mcp__ops-mcp__resource_usage,…"` や `/permissions` で許可 |
| `.mcp.json` に書いたのに stdio 扱いでエラー | `"type": "http"` が無い | `url` だけだと stdio 解釈。`"type": "http"` を付ける |
| 「サーバが混雑しています」 | 外部コマンドの同時数上限（意図した動作） | 少し待って再実行。モデルは通常自分で再試行する |

## ツールの結果がおかしい

| 症状 | 原因 |
|---|---|
| `ログを読む権限がありません: auth` | サーバを動かしているユーザーが `adm` グループでない（`id` で確認）。syslog / auth / kern / dmesg は `root:adm 640` |
| `listening_ports` の `pid` / `process` が `null` | 他ユーザー（root 等）のソケットは非 root だと取れない。仕様（`null` に縮退） |
| `top_processes` で `name` が `MainThread` ばかり | ランタイム（node 等）のスレッド名。`exe` 列で判別する |
| `top_processes` の `cpu_percent` が 100 を超える | プロセス単位は **1コア=100%**。マルチスレッドなら超える |
| 値が古い | TTL キャッシュ（2〜10秒）。厳密にするならサーバの `MCP_CACHE_TTL_SCALE=0` |
| `service_status` が `ユニットが見つかりません` | 実在しない / 未ロード。`.service` を付けても付けなくても可 |
| `journal_recent` の `unit` が `wsl-pro.service` 等 | WSL 固有のサービス。正常 |

## サーバ側（起動しない・止まらない）

| 症状 | 原因 | 対処 |
|---|---|---|
| `uv: command not found` | uv 未導入 / PATH 外 | uv を導入するか `UV=/path/to/uv make …`（[`../../server/docs/01-setup.md`](../../server/docs/01-setup.md)） |
| `ERROR: port 8848 is already in use by another process` | 別プロセスが使用中 | `ss -ltnp \| grep 8848`。`MCP_PORT=9000 make start` で一時的に別ポート |
| `ERROR: server exited during startup` + トレースバック | 設定ミス（例 `MCP_PORT=abc`）など | 表示されたログ末尾を読む。`run/server.log` に全文 |
| `ImportError: cannot import name 'types' from partially initialized module 'mcp'` | **インストール中断で壊れた `.venv`** | `make clean && make setup` |
| `TypeError: MCPServer.__init__() got an unexpected keyword argument 'port'` | トランスポート引数を `MCPServer(...)` に渡している | `host`/`port` は `mcp.run(...)` に渡す（コンストラクタではない） |
| `make stop` 後もプロセスが残る | `uv run` は子として python を起動する | `serverctl.sh` は SIGTERM の後、SIGKILL 時にプロセスグループごと落とす。それでも残るなら `ps -ef \| grep server.py` |

## Python の MCP クライアント（`smoke_test.py` 等）を自作する場合

（SDK のトラブルシューティング文書より。この環境では未再現）

- `ExceptionGroup: unhandled errors in a TaskGroup` が出ても本当のエラーではない。**最後の1行**を読む。`async with Client(...)` の**内側**で `MCPError` を捕まえると包まれない
- `Session not found` は旧プロトコル（2025-11-25 以前）のクライアントでサーバ再起動/期限切れのとき。再接続する。2026-07-28 ではセッションが無いので出ない

## それでも分からないとき

```bash
# 1. サーバ側の生ログ
make -C ../server logs

# 2. Claude を介さず生の JSON-RPC を叩く（docs/00-architecture.md §4）
curl -i -X POST http://127.0.0.1:8848/mcp -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' -d '{}'

# 3. サーバ単体の健全性（Claude・ネットワークを除外）
make -C ../server smoke
```

# 03. 運用（起動・停止・ログ・設定変更）

## make ターゲット

| コマンド | 内容 |
|---|---|
| `make setup` | `uv sync`（`.venv` と依存）＋ `config/server.env` の用意 |
| `make run` | フォアグラウンド起動（Ctrl-C で停止）。動作を見ながら試すとき |
| `make start` | バックグラウンド起動。ポートが開くまで待ち、失敗ならログ末尾を表示 |
| `make stop` | 停止（SIGTERM → 最大10秒待つ → 残っていればプロセスグループを SIGKILL） |
| `make restart` | 停止 → 起動 |
| `make status` | 起動状態。起動中 exit 0 / 停止中 exit 3 |
| `make logs` | `run/server.log` を追う（Ctrl-C で抜ける） |
| `make smoke` | MCP プロトコル疎通テスト（要: 起動済み） |
| `make load` | 並行リクエストの競合テスト（要: 起動済み） |
| `make test` | smoke + load |
| `make clean` | 停止して `.venv` と `run/` を削除 |

`smoke` / `load` の接続先は `config/server.env` の `MCP_PORT` に追従する。上書きは `make smoke MCP_URL=http://…/mcp`。

## ファイル

| パス | 内容 |
|---|---|
| `run/server.pid` | バックグラウンド起動時の PID（実体は `uv` プロセス。子が python） |
| `run/server.log` | 標準出力・標準エラー（uvicorn のアクセスログ、SDK と `ops.*` のログ） |
| `config/server.env` | 設定（git 管理外）。書式は [`01-setup.md`](01-setup.md) |

## `serverctl.sh` の安全動作（実測で確認済み）

| 状況 | 挙動 |
|---|---|
| 起動中に `make start` | `already running (pid N)` で何もしない（exit 0） |
| 別プロセスが同じポートを使用中に `make start` | `ERROR: port 8848 is already in use by another process`（exit 非0） |
| 起動に失敗して落ちた | ログ末尾20行を表示して PID ファイルを消す |
| **PID ファイルが古く、別プロセスがその PID を使っている** | `cmdline` に `server.py` を含むか確認するため、**無関係なプロセスは kill しない**（`not running` と表示） |

## ログの読み方

```
INFO:     127.0.0.1:35954 - "POST /mcp HTTP/1.1" 200 OK        ← アクセスログ。ツール名は出ない
WARNING  Invalid Host header: ...                              ← 421 の理由。クライアントには出ない
WARNING  listening on 0.0.0.0 (not localhost) with NO authentication; allowed hosts: [...]
WARNING  command failed rc=...: [...] stderr=...               ← 外部コマンド失敗の詳細（クライアントには一般化して返る）
ERROR    unexpected error in <tool>  + traceback               ← 想定外の例外（クライアントには「内部エラー」）
```

- アクセスログには**ツール名も引数も出ない**。何が呼ばれたかを見たいときは `server_stats` のカウンタを使う（`make load` が使っている）。
- ログレベルは `MCP_LOG_LEVEL=DEBUG` で詳細化。

## よくある変更

### ポートを変える
`config/server.env` の `MCP_PORT` を変えて `make restart`。クライアント側の URL（`client/config/endpoint.env`）も合わせる。

### 別マシンから繋がせる
1. `config/server.env`: `MCP_HOST=0.0.0.0` と `MCP_ALLOWED_HOSTS=<サーバのIP>`
2. `make restart`（`run/server.log` に `WARNING listening on 0.0.0.0 ... NO authentication` が出る）
3. クライアント側の URL をサーバの IP にする

**`MCP_ALLOWED_HOSTS` を忘れると全リクエストが `421 Misdirected Request` になる**（再現・診断は [`../../client/docs/02-remote-host.md`](../../client/docs/02-remote-host.md)）。
認証が無いので、信頼できる LAN 内に限ること。WSL2 の IP は再起動で変わる。

### キャッシュを切る / 変える
`MCP_CACHE_TTL_SCALE=0`（無効。重複排除は残る）や `0.5`（TTL を半分）。個別の TTL は `ops/concurrency.py` の `TTL_FAST / TTL_NORMAL / TTL_LOG`。

### 見せるログを変える
`ops/collectors.py` の `LOG_ALLOWLIST` と `server.py` の `LogName` を**両方**変える（ずれると起動時の assert で落ちる）。

## 本番運用への注意（トライアル範囲外）

- 認証・レート制限は無い。公開するなら SDK の `run/authorization` を参照
- 1プロセス前提。`uvicorn --workers N` に変えると並行制御が worker ごとに分断される（→ [`04-concurrency.md`](04-concurrency.md)）
- systemd ユニット化などのデーモン管理は未対応（`make start` は簡易な常駐）

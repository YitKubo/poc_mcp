# 05. トラブルシューティング（サーバ側）

クライアント（Claude Code）側の問題は、クライアント側のドキュメントにある（クライアントは別ディレクトリ・別端末で独立している）。
サーバ単体の健全性は Claude もネットワークも除外して **`make smoke`** で確認できる。

## 起動しない・止まらない

| 症状 | 原因 | 対処 |
|---|---|---|
| `uv: command not found` | uv 未導入 / PATH 外 | uv を導入するか `UV=/path/to/uv make …`（[`01-setup.md`](01-setup.md)） |
| `ERROR: port 8848 is already in use by another process` | 別プロセスが使用中 | `ss -ltnp \| grep 8848`。`MCP_PORT=9000 make start` で一時的に別ポート |
| `ERROR: server exited during startup` + トレースバック | 設定ミス（例 `MCP_PORT=abc`）など | 表示されたログ末尾を読む。`run/server.log` に全文 |
| `ImportError: cannot import name 'types' from partially initialized module 'mcp'` | **インストール中断で壊れた `.venv`** | `make clean && make setup` |
| `TypeError: MCPServer.__init__() got an unexpected keyword argument 'port'` | トランスポート引数を `MCPServer(...)` に渡している | `host`/`port` は `mcp.run(...)` に渡す（コンストラクタではない） |
| `make stop` 後もプロセスが残る | `uv run` は子として python を起動する | `serverctl.sh` は SIGTERM の後、SIGKILL 時にプロセスグループごと落とす。それでも残るなら `ps -ef \| grep server.py` |
| `already running (pid N)` | 冪等動作（正常） | 再起動なら `make restart` |

## クライアントから繋がらないと言われた

| クライアントの症状 | サーバ側で見ること |
|---|---|
| TCP が繋がらない | `make status`（`running` か / `port_open=yes` か）。別マシンから繋ぐなら `MCP_HOST=0.0.0.0` になっているか |
| `421 Misdirected Request` | **`MCP_ALLOWED_HOSTS` に、クライアントが URL に書いているホスト部が入っているか**。`run/server.log` に `WARNING Invalid Host header` が出ているはず。手順は共有ドキュメント [`../../docs/10-remote-host.md`](../../docs/10-remote-host.md) |
| `404` | パスは `/mcp`（`streamable_http_path` を変えていなければ） |
| 「サーバが混雑しています」 | 外部コマンドの同時数上限に達した（意図した動作）。`server_stats` の `command.busy_rejected` で回数を確認 |

## ツールの結果がおかしい

| 症状 | 原因 | 対処 |
|---|---|---|
| `ログを読む権限がありません: auth` | サーバを動かすユーザーが `adm` グループでない | `id` で確認。syslog / auth / kern / dmesg は `root:adm 640` |
| `listening_ports` の `pid` が `null` | 他ユーザーのソケットは非 root だと取れない | 仕様（`null` に縮退） |
| 値が古い | TTL キャッシュ | `MCP_CACHE_TTL_SCALE=0` |
| `journalctl が … 失敗しました` | journal を読めない / systemd が無い | `run/server.log` に stderr の詳細（クライアントには一般化して返る） |

## 調べ方

```bash
make status        # 起動状態
make logs          # 生ログを追う（アクセスログ・WARNING・トレースバック）
make smoke         # サーバ単体の健全性（24項目）
make load          # 並行リクエストの競合（22項目）

# 生の JSON-RPC を叩く（プロトコルの実物。docs/00-architecture.md §4）
curl -i -X POST http://127.0.0.1:8848/mcp -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' -d '{}'
```

アクセスログには**ツール名も引数も出ない**。何が呼ばれたかは `server_stats` のカウンタで見る。

## Python の MCP クライアント（`smoke_test.py` 等）を書き換える場合

（SDK のトラブルシューティング文書より。この環境では未再現）

- `ExceptionGroup: unhandled errors in a TaskGroup` が出ても本当のエラーではない。**最後の1行**を読む。`async with Client(...)` の**内側**で `MCPError` を捕まえると包まれない
- `Session not found` は旧プロトコル（2025-11-25 以前）のクライアントでサーバ再起動/期限切れのとき。再接続する。2026-07-28 ではセッションが無いので出ない

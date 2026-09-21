# 02. トラブルシューティング（クライアント側）

まず **`make check`**（Claude 抜きの3段階チェック）で切り分ける。どこで止まるかで原因の層が決まる。
サーバ側の起動・設定の問題は、サーバを動かしている側のドキュメント（`server/docs/05-troubleshooting.md`）にある。

## `make check` の失敗

| 表示 | 原因 | 対処 |
|---|---|---|
| `1. TCP connect ...... FAIL` | ポートに繋がらない: サーバ未起動 / ポート違い / 待受アドレス / FW | **サーバ側の端末で** `make status`。URL のポート・ホストを確認。別マシンのサーバなら、サーバが `0.0.0.0` で待ち受けているか |
| `2. HTTP response ..... FAIL (404)` | パスが違う | `MCP_SERVER_URL` の末尾が **`/mcp`** か |
| `2. HTTP response ..... FAIL (421 Misdirected Request)` | **サーバ側**の Host allowlist に接続先が入っていない | サーバ管理者に `MCP_ALLOWED_HOSTS` へ URL のホスト部を追加してもらう。**理由はサーバ側のログにしか出ない**（`WARNING Invalid Host header`）。手順は共有ドキュメント [`../../docs/10-remote-host.md`](../../docs/10-remote-host.md) |
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
| 「サーバが混雑しています」 | サーバ側の外部コマンド同時数上限（意図した動作） | 少し待って再実行。モデルは通常自分で再試行する |

## ツールの結果がおかしい

| 症状 | 原因 |
|---|---|
| `ログを読む権限がありません: auth` | サーバを動かしているユーザーが `adm` グループでない。syslog / auth / kern / dmesg は `root:adm 640`（サーバ側の対処） |
| `listening_ports` の `pid` / `process` が `null` | 他ユーザー（root 等）のソケットは非 root だと取れない。仕様（`null` に縮退） |
| `top_processes` で `name` が `MainThread` ばかり | ランタイム（node 等）のスレッド名。`exe` 列で判別する |
| `top_processes` の `cpu_percent` が 100 を超える | プロセス単位は **1コア=100%**。マルチスレッドなら超える |
| 値が古い | サーバの TTL キャッシュ（2〜10秒）。厳密にするならサーバ側で `MCP_CACHE_TTL_SCALE=0` |
| `service_status` が `ユニットが見つかりません` | 実在しない / 未ロード。`.service` を付けても付けなくても可 |
| `journal_recent` の `unit` が `wsl-pro.service` 等 | WSL 固有のサービス。正常 |

## それでも分からないとき（クライアント側から見えるもの）

```bash
# 1. Claude を介さず、サーバに届くか（3段階）
make check

# 2. 生の JSON-RPC を叩く（URL は自分の接続先に）
curl -i -X POST http://127.0.0.1:8848/mcp -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' -d '{}'
#   400 + JSON-RPC エラー -> サーバは生きていて MCP として応答している
#   421                   -> サーバ側の Host allowlist
#   404                   -> パス違い
#   接続できない          -> サーバ未起動 / ネットワーク

# 3. 登録の状態
make show
make list
```

サーバ内部（ログ・起動）の調査は**サーバ側の端末で**行う（`server/docs/05-troubleshooting.md`）。

# 02. 公開インターフェース仕様

サーバ名 `ops-mcp`。実装は [`../server.py`](../server.py)（定義）と [`../ops/collectors.py`](../ops/collectors.py)（取得ロジック）。
`make smoke` がこの表の全ツールを実データで確認している。

## Tools（9個・すべて `read_only_hint=true`, `open_world_hint=false`）

| ツール | 引数（範囲・既定） | 戻り値の要点 | TTL |
|---|---|---|---|
| `system_overview` | なし | `hostname` `os` `kernel` `is_wsl` `boot_time`(UTC) `uptime_seconds` `cpu_count_logical/physical` `load_average{1m,5m,15m}` | 10s |
| `resource_usage` | `interval`: 0.1〜5.0（1.0） | `cpu{percent, per_cpu_percent[]}` `memory{total_mb, used_mb, available_mb, percent}` `swap{...}` `sampled_over_seconds`。**`interval` 秒かけて CPU を計測する** | 2s |
| `disk_usage` | `path`: 絶対パス（`/`） | `path` `total_mb` `used_mb` `free_mb` `percent` `mounts[]` | 10s |
| `top_processes` | `sort_by`: `cpu`\|`memory`（cpu）、`limit`: 1〜50（10） | `result[]` = `pid` `name` `exe` `user` `cpu_percent` `memory_percent` `rss_mb`。`cpu_percent` は **1コア=100%** で 100 超がありうる | 2s |
| `listening_ports` | なし | `result[]` = `address` `port` `pid` `process`。**他ユーザーのソケットは pid/process が `null`**（非 root） | 10s |
| `service_status` | `name`: systemd ユニット名（下記の書式） | `unit` `description` `load_state` `active_state` `sub_state` `enabled` `main_pid` `active_since` | 10s |
| `tail_log` | `name`: `syslog`\|`auth`\|`kern`\|`dmesg`、`lines`: 1〜1000（50） | `log` `path` `lines_returned` `lines[]` | 3s |
| `journal_recent` | `unit`: 任意（`service_status` と同じ書式）、`priority`: 任意 `emerg…debug`（指定以上の重大度）、`lines`: 1〜500（50） | `count` `entries[]` = `time`(UTC) `priority` `unit` `message`(≤500字) | 3s |
| `server_stats` | なし | 並行制御のカウンタ（→ [`04-concurrency.md`](04-concurrency.md)）。**キャッシュしない** | — |

- **戻り値の形**: `dict` を返すツールは `structured_content` にそのまま入る。`list` を返すツール（`top_processes` / `listening_ports`）は **`{"result": [...]}` に包まれる**。
- **鮮度**: TTL は「その間は同じ値を返す」という意味（古さと負荷のトレードオフ）。即時性が要るなら `MCP_CACHE_TTL_SCALE=0`。
- **ユニット名の書式**: `^[A-Za-z0-9][A-Za-z0-9@.:_\-]{0,127}$`。先頭が英数字であること（`-` 始まりは外部コマンドにオプションと解釈されうるため拒否）。

### `service_status` の出力例（実測）

```json
{"unit": "cron", "description": "Regular background program processing daemon",
 "load_state": "loaded", "active_state": "active", "sub_state": "running",
 "enabled": "enabled", "main_pid": 182, "active_since": "Mon 2026-09-21 17:22:02 JST"}
```

### エラー

失敗は `is_error=true` で返り、本文が**そのままモデルに見える**。モデルが読んで対処できるよう日本語で原因を書いている。

| 原因 | メッセージの例 | 出どころ |
|---|---|---|
| 型・範囲・enum の違反 | `Input should be 'syslog', 'auth', 'kern' or 'dmesg'` / `less than or equal to 1000` | SDK（Pydantic）。関数に入る前 |
| ユニット名が不正 | `ユニット名が不正です。英数字で始まり…` | `validate_unit` |
| 存在しないユニット | `ユニットが見つかりません: <name>` | `LoadState=not-found` |
| 相対パス | `path は絶対パスで指定してください。` | `disk_usage` |
| 権限不足 | `ログを読む権限がありません: <name>` | ファイル読み取り |
| 外部コマンドの失敗・時間切れ | `journalctl が 15 秒でタイムアウトしました。` | `run_command` |
| **混雑** | `サーバが混雑しています。少し待って再実行してください。` | 外部コマンドの同時数上限 |
| 想定外 | `内部エラーが発生しました。サーバログを確認してください。` | 詳細は**サーバログだけ** |

## Resources

| URI | 内容 | mime |
|---|---|---|
| `ops://host` | `system_overview` と同じ JSON | `application/json` |
| `ops://logs` | 許可ログの一覧（`name` `path` `exists` `readable` `size_bytes`） | `application/json` |
| `ops://logs/{name}` | 許可ログの末尾100行（テンプレート） | text |

SDK の既定（`resource_security`）でパストラバーサル・絶対パス・NUL バイトを含む URI パラメータは拒否される。さらに `name` は許可リストで照合する。

## Prompts

| 名前 | 内容 |
|---|---|
| `health_check` | 各ツールで状態を集め、`journal_recent(priority=err)` も見て、異常を根拠つきで指摘させる |
| `investigate_load` | ロードアベレージ・CPU・メモリ・上位プロセスから負荷の原因を調べさせる |

## 安全設計

- **書き込み系ツールは無い**（停止・再起動・削除・任意コマンド実行は作らない）
- 外部コマンドは `systemctl show` と `journalctl` のみ。`shell=False`、引数は配列の1要素、`--` でオプション終端、`LC_ALL=C`
- ログは `LOG_ALLOWLIST` のキーだけ（`syslog` `auth` `kern` `dmesg`）。パスを引数で受け取らない
- 出力から制御文字（ANSI エスケープ等）を除去（journal には色付きログがそのまま入っていたため。修正前は `smoke` の該当項目が FAIL することを確認済み）
- `top_processes` は `cmdline` を出さず `exe` のみ（コマンドライン引数に秘密が入りうるため）
- **`auth` ログは機微**（ログイン試行・sudo 履歴）。不要なら `ops/collectors.py` の `LOG_ALLOWLIST` と `server.py` の `LogName` から外す（両者は import 時に一致を assert している）
- **ログ本文は外部入力**: 外部由来のテキストが含まれうるため、モデルに対するプロンプトインジェクションの経路になりうる

## ツールを追加するには

1. `ops/collectors.py` に取得関数を書く（失敗は `ToolError`、外部コマンドは `run_command` 経由）
2. `server.py` に **`def`（`async def` ではない）** でツールを書き、`cache.call((ツール名, 引数…), TTL, lambda: …)` で包む
3. `scripts/smoke_test.py` の `EXPECTED_TOOLS` と `cases` に追加。並行で重い処理なら `load_test.py` にも

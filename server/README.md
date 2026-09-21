# server — ops-mcp（サーバ運用ツール MCP サーバ）

このホストの状態（CPU・メモリ・ディスク・プロセス・ポート・systemd・ログ）を、**読み取り専用**で Claude に見せる MCP サーバ。
Streamable HTTP で待ち受け、別プロセス（別ターミナルの Claude Code）から URL で繋ぐ。

- **このディレクトリ（`server/`）だけで自己完結**する。操作はここで `make` を使う（`make help`）。Claude Code から繋ぐ側は別ディレクトリ `client/` で独立している
- 全体像と図（共有）: [`../docs/00-architecture.md`](../docs/00-architecture.md)

## 3分で起動

```bash
make setup      # uv で .venv を作り依存を導入（config/server.env も作る）
make start      # バックグラウンドで起動 -> http://127.0.0.1:8848/mcp   （make up = setup + start）
make smoke      # MCP プロトコル疎通テスト（24 項目）
make load       # 並行リクエストの競合テスト（22 項目）
make stop
```

`make help` でターゲット一覧。**前提**: `uv`・`make`・Python ≥ 3.10（→ [`docs/01-setup.md`](docs/01-setup.md)）。

## ファイル

| パス | 役割 |
|---|---|
| `server.py` | `MCPServer("ops-mcp")` の定義（tools / resources / prompts）と起動 |
| `ops/collectors.py` | OS から情報を集める層。`shell=False`・許可リスト・入力検証 |
| `ops/concurrency.py` | 並行制御。TTL キャッシュ + single-flight、外部コマンドの同時数制限 |
| `pyproject.toml`, `uv.lock` | 依存（`mcp[cli]>=2,<3`, `psutil`）。`uv sync` で `.venv` を作る |
| `config/server.env.example` | 設定の雛形（`make setup` が `server.env` にコピー。`server.env` は git 管理外） |
| `scripts/serverctl.sh` | 起動・停止・状態（Makefile から呼ぶ） |
| `scripts/smoke_test.py` | Claude 抜きの MCP 疎通テスト |
| `scripts/load_test.py` | Claude 抜きの並行リクエスト競合テスト |
| `run/` | 実行時の PID ファイルとログ（git 管理外） |

## ドキュメント

| | |
|---|---|
| [`docs/01-setup.md`](docs/01-setup.md) | 環境構築（uv / venv / 設定） |
| [`docs/02-tools-spec.md`](docs/02-tools-spec.md) | 公開する tools / resources / prompts の仕様 |
| [`docs/03-operations.md`](docs/03-operations.md) | 起動・停止・ログ・設定変更・外部公開 |
| [`docs/04-concurrency.md`](docs/04-concurrency.md) | 並行リクエストで起きる競合と対処、検証結果 |
| [`docs/05-troubleshooting.md`](docs/05-troubleshooting.md) | 起動しない・クライアントから繋がらないときの切り分け |

別マシンに公開する手順（サーバ設定＋クライアント設定の両方が要る）は共有ドキュメント [`../docs/10-remote-host.md`](../docs/10-remote-host.md)。

## 注意

- **認証なし**。既定の待受は `127.0.0.1`（同一ホストのみ）。外に開くと誰でも読み取りツールを呼べる。
- 全ツール read-only だが、`auth` ログなど**機微な情報を返しうる**（→ `docs/02-tools-spec.md`）。

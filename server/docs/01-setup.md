# 01. 環境構築

## 前提

| 必要なもの | 用途 | 確認 |
|---|---|---|
| Linux（WSL2 可） | 対象ホスト | `uname -a` |
| Python ≥ 3.10 | 実行（この環境は 3.12.3） | `python3 --version` |
| **uv** | 依存管理と実行 | `uv --version` |
| make | 操作の入口 | `make --version` |
| systemd | `service_status` / `journal_recent` が使う（無くても他のツールは動く） | `systemctl is-system-running` |

### uv の導入

uv は**この手順書では自動導入しない**（システムへの導入はあなたの判断）。未導入なら公式の手順に従う。例:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh     # 公式インストーラ（~/.local/bin/uv に入る）
```

PATH に無い場所の uv を使う場合は、`UV=/path/to/uv make setup` のように環境変数で指定できる（Makefile は `UV ?= uv`）。
検証は uv 0.12.17 で行った。

## `make setup` がやること

```bash
uv sync                       # server/.venv を作り、uv.lock どおりに依存を導入
cp config/server.env.example config/server.env   # 無ければ作る
```

- 依存: `mcp[cli]>=2,<3`（検証時 **mcp 2.2.0**）、`psutil>=5.9`（検証時 7.2.2）。`uv.lock` で固定しているので再現できる。
- `mcp` は **v2 系**。v1 と API が違う（`FastMCP` → `MCPServer` など）ので、`<3` の上限は外さないこと。
  v1 系の記事・サンプルはそのままでは動かない（→ [`../../docs/90-mcp-notes.md`](../../docs/90-mcp-notes.md)）。

> **なぜ venv / uv か**: Ubuntu 24.04 は PEP 668（`EXTERNALLY-MANAGED`）により、システムの `pip install` を拒否する。
> uv はプロジェクト専用の `.venv` を作るのでこの問題に当たらない。

## 動作確認

```bash
make start       # started (pid ...)  http://127.0.0.1:8848/mcp
make status      # running (pid ...)  port_open=yes
make smoke       # 24 passed, 0 failed
make load        # 22 passed, 0 failed
```

手で直接叩くなら（サーバ起動中）: [`../../docs/00-architecture.md` §4](../../docs/00-architecture.md) の curl。

## 設定項目（`config/server.env`）

| 変数 | 既定 | 意味 |
|---|---|---|
| `MCP_HOST` | `127.0.0.1` | 待受アドレス。`0.0.0.0` にすると外部から届く（要 `MCP_ALLOWED_HOSTS`） |
| `MCP_PORT` | `8848` | 待受ポート |
| `MCP_ALLOWED_HOSTS` | 空 | `MCP_HOST` が localhost 以外のときに許可する Host（カンマ区切り。例 `192.168.1.10`） |
| `MCP_LOG_LEVEL` | `INFO` | ログレベル |
| `MCP_CACHE_TTL_SCALE` | `1.0` | キャッシュ TTL の倍率。`0` でキャッシュ無効（single-flight は残る） |

書式は `KEY=VALUE`（クォートしない）。`serverctl.sh` がシェルの `source` で読む。

## 補足: `uv run` は exec しない

この環境の uv（0.12.17）では、`uv run python server.py` は python を**子プロセスとして起動**する（uv 自身が親のまま残る）。
`make stop` は uv に SIGTERM を送り、uv が子へ転送するため両方止まる（実測で確認）。
SIGKILL 経路では子が孤児になりうるので、`serverctl.sh` はフォールバックでプロセスグループごと kill する。

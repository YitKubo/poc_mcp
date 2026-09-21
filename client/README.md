# client — MCP サーバへ繋ぐ側（Claude Code）

`server/` の MCP サーバ（`ops-mcp`）に、別ターミナルの Claude Code から HTTP で接続するための設定・スクリプト・手順。
**Python 不要**（要: `claude`・`curl`・`make`）。このディレクトリ一式を別端末にコピーして、接続先 URL だけ書き換えれば同じ手順で使える。

- 全体像と図: [`../docs/00-architecture.md`](../docs/00-architecture.md)
- 繋がれる側: [`../server/README.md`](../server/README.md)

## 使い方（サーバを起動済みの状態で）

```bash
make config     # config/endpoint.env を作る（接続先を確認・編集）
make check      # Claude 抜きで到達性を確認: TCP -> HTTP -> MCP tools/list
make add        # claude mcp add で登録
cd client && claude      # ★ 新しいセッションを起動（local scope はこのディレクトリで）
                         #   -> /mcp で ops-mcp が connected と出れば成功
make remove     # 登録解除
```

`make help` でターゲット一覧。

## ファイル

| パス | 役割 |
|---|---|
| `config/endpoint.example.env` | 接続先の雛形。`make config` が `endpoint.env` にコピー（`endpoint.env` は git 管理外） |
| `config/mcp.json.template` | `.mcp.json` 方式で登録する場合のテンプレート |
| `scripts/check_reachable.sh` | 到達性チェック（curl のみ） |
| `scripts/add_mcp.sh` / `remove_mcp.sh` | `claude mcp add` / `remove` のラッパー（登録済みなら冪等） |
| `scripts/_common.sh` | 設定の読み込み。**優先順: 環境変数 > `endpoint.env` > `endpoint.example.env`** |

一時的に接続先を変えるだけなら設定ファイルを触らずに:

```bash
MCP_SERVER_URL=http://192.168.1.10:8848/mcp make check
```

## ドキュメント

| | |
|---|---|
| [`docs/01-connect.md`](docs/01-connect.md) | 別ターミナルから接続する手順（本体）。scope の違い、実測した出力 |
| [`docs/02-remote-host.md`](docs/02-remote-host.md) | 別マシンへ広げる場合の差分（`421` の再現と対処） |
| [`docs/03-troubleshooting.md`](docs/03-troubleshooting.md) | 症状別の切り分け |
